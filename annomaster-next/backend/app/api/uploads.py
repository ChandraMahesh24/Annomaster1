"""
Upload endpoints — single / folder / zip / video, plus batch list & delete.

Ported rules (one note each):
  • Every upload source registers images through the SAME helper, so none can
    silently skip DB registration (the original's video bug).
  • Duplicate (same md5 in project) is not written — no file-without-row drift.
  • Files never move: lifecycle is DB columns, uploads only ever add.
  • Video extraction is a background job (Celery when available, else inline).
"""
import io
import tempfile
import zipfile
from pathlib import Path

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import paths
from app.core.deps import Membership, workspace_role
from app.core.db import get_session
from app.models.image import Image
from app.models.workspace import Workspace
from app.schemas.upload import (
    AssignmentBrief, BatchListItem, BatchOut, JobEnqueued, UploadResult,
)
from app.services import batches as batch_svc
from app.services import storage
from app.services.media import ALLOWED_IMG
from app.services.audit import log_action

router = APIRouter(prefix='/workspaces/{workspace_id}/projects/{project}',
                   tags=['uploads'])

EDIT = ('owner', 'editor')
READ = ('owner', 'editor', 'viewer')


def _folder(session: Session, workspace_id: int) -> str:
    ws = session.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Workspace not found')
    return ws.folder_name


def _find_batch(folder: str, project: str, upload_id: int) -> dict | None:
    return next((b for b in storage.load_uploads(folder, project)
                 if b['upload_id'] == upload_id), None)


# ── Create an (empty) batch ───────────────────────────────────────────────────
@router.post('/upload/create_batch', response_model=BatchOut, status_code=201)
def create_batch(workspace_id: int, project: str,
                 member: Membership = Depends(workspace_role(*EDIT)),
                 session: Session = Depends(get_session)):
    folder = _folder(session, workspace_id)
    b = batch_svc.create_batch(session, folder, project, workspace_id,
                               'images', member.user.id)
    return BatchOut(**b)


# ── Single image ──────────────────────────────────────────────────────────────
@router.post('/upload', response_model=UploadResult)
def upload_one(workspace_id: int, project: str, request: Request,
               file: UploadFile = File(...), upload_id: int | None = Form(None),
               member: Membership = Depends(workspace_role(*EDIT)),
               session: Session = Depends(get_session)):
    folder = _folder(session, workspace_id)
    batch = (_find_batch(folder, project, upload_id) if upload_id else None) \
        or batch_svc.create_batch(session, folder, project, workspace_id, 'images', member.user.id)

    data = file.file.read()
    outcome = batch_svc.save_and_register(
        session, folder=folder, project=project, workspace_id=workspace_id,
        batch=batch, uploader_id=member.user.id, filename=file.filename or 'image', data=data)
    log_action(session, 'upload.image', user_id=member.user.id, workspace_id=workspace_id,
               project=project, ip=request.client.host if request.client else None)
    return UploadResult(upload_id=batch['upload_id'], job_name=batch['job_name'],
                        saved=int(outcome == 'saved'), duplicates=int(outcome == 'duplicate'))


# ── Folder (images + optional labels + data.yaml/classes.txt) ────────────────
@router.post('/upload/folder', response_model=UploadResult)
def upload_folder(workspace_id: int, project: str, request: Request,
                  files: list[UploadFile] = File(...), upload_id: int | None = Form(None),
                  member: Membership = Depends(workspace_role(*EDIT)),
                  session: Session = Depends(get_session)):
    folder = _folder(session, workspace_id)
    batch = (_find_batch(folder, project, upload_id) if upload_id else None) \
        or batch_svc.create_batch(session, folder, project, workspace_id, 'folder', member.user.id)

    # split incoming into images / label .txt / class list (data.yaml|classes.txt).
    # A YOLO folder carries its OWN class ordering, so we merge those names into
    # the project and remap every label's class column (see batches.py) — else a
    # source "0=person" silently becomes whatever class 0 is in this project.
    imgs: dict[str, tuple[str, bytes]] = {}
    lbls: dict[str, bytes] = {}
    cls_names: list[str] = []
    for f in files:
        name = Path(f.filename or '').name
        ext = Path(name).suffix.lower()
        if ext in ALLOWED_IMG:
            imgs[Path(name).stem] = (name, f.file.read())
        elif ext == '.txt' and name != 'classes.txt':
            lbls[Path(name).stem] = f.file.read()
        elif name in ('data.yaml', 'data.yml'):
            cls_names = batch_svc.class_names_from_yaml(f.file.read())
        elif name == 'classes.txt':
            cls_names = batch_svc.class_names_from_txt(f.file.read())

    remap = batch_svc.merge_classes_and_remap(folder, project, cls_names) if cls_names else {}

    saved = dups = annotated = 0
    lbl_dir = paths.batch_lbl_dir(folder, project, batch['job_name'])
    for stem, (name, data) in imgs.items():
        has_lbl = stem in lbls and bool(lbls[stem].strip())
        outcome = batch_svc.save_and_register(
            session, folder=folder, project=project, workspace_id=workspace_id,
            batch=batch, uploader_id=member.user.id, filename=name, data=data,
            is_annotated=has_lbl)
        if outcome == 'duplicate':
            dups += 1
            continue
        saved += 1
        if stem in lbls:
            (lbl_dir / f'{Path(batch_svc.safe_filename(name)).stem}.txt').write_bytes(
                batch_svc.remap_label_bytes(lbls[stem], remap))
            if has_lbl:
                annotated += 1

    log_action(session, 'upload.folder', user_id=member.user.id, workspace_id=workspace_id,
               project=project, detail={'saved': saved}, ip=request.client.host if request.client else None)
    return UploadResult(upload_id=batch['upload_id'], job_name=batch['job_name'],
                        saved=saved, duplicates=dups, annotated=annotated)


# ── ZIP import ────────────────────────────────────────────────────────────────
@router.post('/import', response_model=UploadResult)
def import_zip(workspace_id: int, project: str, request: Request,
               file: UploadFile = File(...),
               member: Membership = Depends(workspace_role(*EDIT)),
               session: Session = Depends(get_session)):
    folder = _folder(session, workspace_id)
    batch = batch_svc.create_batch(session, folder, project, workspace_id, 'zip', member.user.id)
    lbl_dir = paths.batch_lbl_dir(folder, project, batch['job_name'])

    saved = dups = annotated = 0
    try:
        with zipfile.ZipFile(io.BytesIO(file.file.read())) as zf:
            names = zf.namelist()
            labels = {Path(n).stem: zf.read(n)
                      for n in names
                      if Path(n).suffix.lower() == '.txt' and Path(n).name != 'classes.txt'}
            # Extract the dataset's own class ordering, then merge + build a remap
            # so label class ids are rewritten to this project's ids (as folder does).
            cls_names: list[str] = []
            for n in names:
                base = Path(n).name
                if base in ('data.yaml', 'data.yml'):
                    cls_names = batch_svc.class_names_from_yaml(zf.read(n))
                    break
                if base == 'classes.txt':
                    cls_names = batch_svc.class_names_from_txt(zf.read(n))
            remap = batch_svc.merge_classes_and_remap(folder, project, cls_names) if cls_names else {}
            for n in names:
                if Path(n).suffix.lower() not in ALLOWED_IMG:
                    continue
                stem = Path(n).stem
                has_lbl = stem in labels and bool(labels[stem].strip())
                outcome = batch_svc.save_and_register(
                    session, folder=folder, project=project, workspace_id=workspace_id,
                    batch=batch, uploader_id=member.user.id, filename=Path(n).name,
                    data=zf.read(n), is_annotated=has_lbl)
                if outcome == 'duplicate':
                    dups += 1
                    continue
                saved += 1
                if stem in labels:
                    (lbl_dir / f'{stem}.txt').write_bytes(
                        batch_svc.remap_label_bytes(labels[stem], remap))
                    if has_lbl:
                        annotated += 1
    except zipfile.BadZipFile:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Not a valid ZIP file')

    log_action(session, 'upload.zip', user_id=member.user.id, workspace_id=workspace_id,
               project=project, detail={'saved': saved}, ip=request.client.host if request.client else None)
    return UploadResult(upload_id=batch['upload_id'], job_name=batch['job_name'],
                        saved=saved, duplicates=dups, annotated=annotated)


# ── List batches ──────────────────────────────────────────────────────────────
@router.get('/uploads', response_model=list[BatchListItem])
def list_uploads(workspace_id: int, project: str,
                 member: Membership = Depends(workspace_role(*READ)),
                 session: Session = Depends(get_session)):
    """
    One rich card per batch — the Active Work panel. For each batch we report the
    annotated/null/raw breakdown (drives the progress bar), whether it has been
    added to a dataset (fully or partially), who uploaded it, and its current
    assignment + progress (which annotator, how far along). Ported from the
    original's _loadUploadBatches payload.
    """
    from app.models.user import User
    from app.models.assignment import Assignment

    folder = _folder(session, workspace_id)
    out = []
    for b in storage.load_uploads(folder, project):
        if not paths.batch_job_dir(folder, project, b['job_name']).exists():
            continue
        rows = session.execute(
            select(Image.is_annotated, Image.is_null, Image.status).where(
                Image.workspace_id == workspace_id, Image.project == project,
                Image.batch_id == b['batch_db_id'])
        ).all()
        total = len(rows)
        # annotated = has real boxes (not a null/background mark); null = empty .txt
        annotated = sum(1 for a, n, _ in rows if a and not n)
        null_cnt = sum(1 for a, n, _ in rows if n)
        in_ds_cnt = sum(1 for _, _, s in rows if s == 'in_dataset')
        pending = total - annotated - null_cnt
        # Fully in dataset = every non-raw image has been added and nothing is
        # left to annotate. Partial = some added but work still remains.
        in_dataset = in_ds_cnt > 0 and pending == 0 and in_ds_cnt >= (annotated + null_cnt)
        partial_dataset = in_ds_cnt > 0 and not in_dataset

        uploader_name = None
        if b.get('uploaded_by'):
            u = session.get(User, b['uploaded_by'])
            uploader_name = u.username if u else None

        assignment = None
        a = session.scalar(select(Assignment).where(
            Assignment.batch_id == b['batch_db_id']))
        if a:
            au = session.get(User, a.assigned_to)
            pct = round(a.done_images / a.total_images * 100) if a.total_images else 0
            assignment = AssignmentBrief(
                assigned_to=a.assigned_to, assignee=au.username if au else '?',
                status=a.status, total_images=a.total_images,
                done_images=a.done_images, progress_pct=pct)

        out.append(BatchListItem(
            upload_id=b['upload_id'], batch_db_id=b['batch_db_id'],
            job_name=b['job_name'], source=b['source'],
            total=total, annotated=annotated, pending=pending, null_count=null_cnt,
            in_dataset=in_dataset, partial_dataset=partial_dataset,
            datetime_str=b['job_name'], uploader_name=uploader_name,
            assignment=assignment))
    return out


# ── Delete a batch (files + rows) ────────────────────────────────────────────
@router.delete('/uploads/{upload_id}', status_code=204)
def delete_upload(workspace_id: int, project: str, upload_id: int, request: Request,
                  member: Membership = Depends(workspace_role(*EDIT)),
                  session: Session = Depends(get_session)):
    import shutil
    folder = _folder(session, workspace_id)
    b = _find_batch(folder, project, upload_id)
    if b:
        # DB rows for this batch, then the on-disk job dir, then the json entry.
        for img in session.scalars(select(Image).where(
                Image.workspace_id == workspace_id, Image.project == project,
                Image.batch_id == b['batch_db_id'])):
            session.delete(img)
        jd = paths.batch_job_dir(folder, project, b['job_name'])
        if jd.exists():
            shutil.rmtree(jd, ignore_errors=True)
        storage.save_uploads(folder, project,
                             [x for x in storage.load_uploads(folder, project)
                              if x['upload_id'] != upload_id])
        log_action(session, 'upload.delete', user_id=member.user.id, workspace_id=workspace_id,
                   project=project, ip=request.client.host if request.client else None)
    return None


# ── Add a batch's annotated images to the dataset (Roboflow-style) ───────────
@router.post('/uploads/{upload_id}/add_to_dataset')
def add_batch_to_dataset(workspace_id: int, project: str, upload_id: int,
                         body: dict, request: Request,
                         member: Membership = Depends(workspace_role(*EDIT)),
                         session: Session = Depends(get_session)):
    from app.services import datasets as ds
    folder = _folder(session, workspace_id)
    batch = _find_batch(folder, project, upload_id)
    if not batch:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Batch not found')
    train = float(body.get('train', 0.70))
    val = float(body.get('val', 0.15))
    test = float(body.get('test', 0.15))
    result = ds.add_batch_to_dataset(
        session, workspace_id, project, batch['batch_db_id'],
        train_r=train, val_r=val, test_r=test, reviewer_id=member.user.id)
    if not result.get('success'):
        # Nothing annotated yet — a 400 the UI shows as a toast, not a crash.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, result.get('error', 'Nothing to add'))
    log_action(session, 'dataset.add_batch', user_id=member.user.id, workspace_id=workspace_id,
               project=project, detail={'upload_id': upload_id, **result},
               ip=request.client.host if request.client else None)
    return result


# ── Assign a batch to an annotator (latest-wins, one per batch) ───────────────
@router.post('/uploads/{upload_id}/assign', response_model=AssignmentBrief)
def assign_batch(workspace_id: int, project: str, upload_id: int, body: dict,
                 request: Request,
                 member: Membership = Depends(workspace_role('owner', 'editor')),
                 session: Session = Depends(get_session)):
    from app.models.assignment import Assignment
    from app.models.user import User
    from app.models.workspace import WorkspaceMember
    folder = _folder(session, workspace_id)
    batch = _find_batch(folder, project, upload_id)
    if not batch:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Batch not found')

    assigned_to = body.get('assigned_to')
    if not assigned_to:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'assigned_to required')
    # The assignee must be a member of this workspace.
    is_member = session.scalar(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == assigned_to))
    if not is_member:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'User is not a workspace member')

    rows = session.execute(select(Image.is_annotated, Image.is_null).where(
        Image.workspace_id == workspace_id, Image.project == project,
        Image.batch_id == batch['batch_db_id'])).all()
    total = len(rows)
    done = sum(1 for a, n in rows if a or n)

    # Latest wins: drop any existing assignment for this batch, then insert.
    for old in session.scalars(select(Assignment).where(
            Assignment.batch_id == batch['batch_db_id'])):
        session.delete(old)
    session.flush()
    a = Assignment(
        workspace_id=workspace_id, project=project, batch_id=batch['batch_db_id'],
        assigned_to=assigned_to, assigned_by=member.user.id,
        note=body.get('note'), total_images=total, done_images=min(done, total),
        status='in_progress' if done > 0 else 'pending')
    session.add(a)
    session.flush()
    log_action(session, 'batch.assign', user_id=member.user.id, workspace_id=workspace_id,
               project=project, detail={'upload_id': upload_id, 'assigned_to': assigned_to},
               ip=request.client.host if request.client else None)
    u = session.get(User, assigned_to)
    pct = round(a.done_images / a.total_images * 100) if a.total_images else 0
    return AssignmentBrief(assigned_to=assigned_to, assignee=u.username if u else '?',
                           status=a.status, total_images=a.total_images,
                           done_images=a.done_images, progress_pct=pct)


@router.delete('/uploads/{upload_id}/assign', status_code=204)
def unassign_batch(workspace_id: int, project: str, upload_id: int,
                   member: Membership = Depends(workspace_role('owner', 'editor')),
                   session: Session = Depends(get_session)):
    from app.models.assignment import Assignment
    folder = _folder(session, workspace_id)
    batch = _find_batch(folder, project, upload_id)
    if batch:
        for old in session.scalars(select(Assignment).where(
                Assignment.batch_id == batch['batch_db_id'])):
            session.delete(old)
    return None


# ── Video → background frame extraction ──────────────────────────────────────
@router.post('/extract_frames', response_model=JobEnqueued)
def extract_frames(workspace_id: int, project: str, request: Request,
                   file: UploadFile = File(...), fps: int = Form(5),
                   fmt: str = Form('jpg'), size: str = Form('original'),
                   split: str = Form('none'),
                   member: Membership = Depends(workspace_role(*EDIT)),
                   session: Session = Depends(get_session)):
    import re
    folder = _folder(session, workspace_id)
    batch = batch_svc.create_batch(session, folder, project, workspace_id, 'video', member.user.id)
    fps = max(1, min(int(fps), 30))
    fmt = 'png' if str(fmt).lower() == 'png' else 'jpg'
    split = split if split in ('train', 'valid', 'test') else None

    # save upload to a temp file for ffmpeg to read. Close the mkstemp fd
    # immediately — on Windows a lingering open handle blocks the later unlink
    # (WinError 32), and ffmpeg opens the path by name anyway.
    import os as _os
    suffix = Path(file.filename or '').suffix or '.mp4'
    _fd, _tmp_name = tempfile.mkstemp(suffix=suffix)
    _os.close(_fd)
    tmp = Path(_tmp_name)
    tmp.write_bytes(file.file.read())
    ts = batch['job_name'].replace('job_', '').replace('-', '').replace('_', '')[:12]
    safe_stem = re.sub(r'[^\w]', '_', Path(file.filename or 'video').stem)[:40]
    stem = f'{safe_stem}_{ts}'

    from app.workers.tasks import extract_frames_task, extract_frames_service
    log_action(session, 'upload.video', user_id=member.user.id, workspace_id=workspace_id,
               project=project, ip=request.client.host if request.client else None)

    # Persist the batch + audit and RELEASE the DB write lock BEFORE the (slow)
    # ffmpeg run. Otherwise the whole extraction holds SQLite's single writer
    # open, and any concurrent write hits "database is locked". (In production
    # the Celery path avoids this entirely by running ffmpeg off-request.)
    session.commit()

    # Use Celery ONLY if the broker (Redis) is actually reachable — not merely
    # because the celery package is installed. Otherwise `.delay()` blocks trying
    # to reach a broker that isn't there. No Redis → run inline.
    from app.core.celery_app import redis_ping
    if extract_frames_task is not None and redis_ping():
        # Celery available → enqueue; the worker registers frames when done.
        task = extract_frames_task.delay(folder, project, batch['job_name'], str(tmp), stem, fps, fmt, size)
        return JobEnqueued(upload_id=batch['upload_id'], job_name=batch['job_name'],
                           task_id=task.id, mode='celery')
    # No broker (dev) → run inline so the flow still works.
    try:
        n = extract_frames_service(folder, project, batch['job_name'], str(tmp), stem, fps, fmt, size)
    except RuntimeError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    finally:
        tmp.unlink(missing_ok=True)
    # register the extracted frames in place (same dedup as every other source)
    ext = f'.{fmt}'
    imgd = paths.batch_img_dir(folder, project, batch['job_name'])
    registered = []
    for f in sorted(imgd.iterdir()):
        if f.suffix.lower() == ext and f.stem.startswith(stem + '_frame'):
            img = batch_svc.register_on_disk(
                session, folder=folder, project=project, workspace_id=workspace_id,
                batch=batch, uploader_id=member.user.id, file_path=f)
            if img is not None:
                registered.append(img)
    # Optional split assignment (matches the original's Output Split setting).
    if split:
        for img in registered:
            img.split = split
    return JobEnqueued(upload_id=batch['upload_id'], job_name=batch['job_name'],
                       mode='inline', frames_extracted=n)
