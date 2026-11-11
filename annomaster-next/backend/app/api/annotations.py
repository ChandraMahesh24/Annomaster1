"""
Annotation read/write + null marking.

Ported rules (one note each):
  • The .txt holds CONFIRMED boxes only; suggested/rejected go to the sidecar —
    so exports can never contain unreviewed predictions.
  • is_annotated flips True only when the .txt has a valid box; is_null writes
    an EMPTY .txt (never a missing file).
  • A save is rejected 409 if another user holds a live lock on the image.
  • First-time annotation increments the covering assignment's done_images
    ATOMICALLY, auto-advancing to 'submitted' at completion.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core import paths
from app.core.deps import Membership, workspace_role
from app.core.db import get_session
from app.core.yolo import (
    is_valid_annotation_file, parse_yolo_label, write_yolo_label,
)
from app.models.assignment import Assignment
from app.models.image import Image
from app.models.workspace import Workspace
from app.services.audit import log_action
from app.services.locks import active_lock  # TTL-aware lookup (B2 locks)
from app.services.suggestions import read_suggestions, write_suggestions

router = APIRouter(prefix='/workspaces/{workspace_id}/projects/{project}',
                   tags=['annotations'])

EDIT = ('owner', 'editor')
READ = ('owner', 'editor', 'viewer')


def _folder(session, workspace_id):
    ws = session.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Workspace not found')
    return ws.folder_name


def _image_row(session, workspace_id, project, rel):
    return session.scalar(select(Image).where(
        Image.workspace_id == workspace_id, Image.project == project,
        Image.rel_path == rel))


def _bump_assignment(session, img: Image, user_id: int):
    """
    Atomic first-annotation increment. `UPDATE … done_images = done_images + 1`
    is evaluated in the DB, so concurrent saves can't lose an increment (the
    read-modify-write the original would have raced). Auto-advances to
    'submitted' when the batch is fully done.
    """
    if img.batch_id is None:
        return
    a = session.scalar(select(Assignment).where(
        Assignment.batch_id == img.batch_id,
        Assignment.assigned_to == user_id))
    if not a:
        return
    session.execute(
        update(Assignment)
        .where(Assignment.id == a.id, Assignment.done_images < Assignment.total_images)
        .values(done_images=Assignment.done_images + 1,
                status='in_progress'))
    session.flush()
    fresh = session.get(Assignment, a.id)
    if fresh and fresh.done_images >= fresh.total_images and fresh.status == 'in_progress':
        fresh.status = 'submitted'


@router.get('/annotations')
def get_annotations(workspace_id: int, project: str, path: str,
                    member: Membership = Depends(workspace_role(*READ)),
                    session: Session = Depends(get_session)):
    folder = _folder(session, workspace_id)
    lbl = paths.label_path_for_image(paths.project_dir(folder, project) / path)
    txt = lbl.read_text(encoding='utf-8', errors='ignore').strip() if lbl.exists() else None
    is_null = txt is not None and txt == ''    # empty .txt == background image

    confirmed = parse_yolo_label(lbl)
    for b in confirmed:
        b['state'] = 'confirmed'   # everything in the .txt is, by definition, confirmed

    lock = active_lock(session, workspace_id, project, path)
    return {
        'bboxes': confirmed,
        'suggestions': read_suggestions(lbl),   # suggested + rejected
        'is_null': is_null,
        'lock': lock.to_dict() if lock else None,
    }


@router.post('/annotations')
def save_annotations(workspace_id: int, project: str, request: Request,
                     body: dict,
                     member: Membership = Depends(workspace_role(*EDIT)),
                     session: Session = Depends(get_session)):
    folder = _folder(session, workspace_id)
    rel = body.get('path', '')
    if not rel:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'path required')

    # Soft-lock: reject if someone else holds a live lock.
    lock = active_lock(session, workspace_id, project, rel)
    if lock and lock.locked_by != member.user.id:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f'Image is being edited by another user')

    # Split by state. Absent state == confirmed (covers pre-feature clients).
    boxes = body.get('bboxes', [])
    confirmed, pending = [], []
    for b in boxes:
        st = (b.get('state') or 'confirmed') if isinstance(b, dict) else 'confirmed'
        (confirmed if st == 'confirmed' else pending).append(b)
    pending.extend(b for b in (body.get('suggestions') or [])
                   if isinstance(b, dict) and b.get('state') in ('suggested', 'rejected'))

    lbl = paths.label_path_for_image(paths.project_dir(folder, project) / rel, create_dir=True)
    write_yolo_label(lbl, confirmed)          # confirmed only
    if 'suggestions' in body or any(isinstance(b, dict) and b.get('state') for b in boxes):
        write_suggestions(lbl, pending)

    is_annotated = is_valid_annotation_file(lbl)
    img = _image_row(session, workspace_id, project, rel)
    if img:
        was_annotated = img.is_annotated
        img.is_annotated = is_annotated
        img.is_null = False
        if is_annotated:
            img.annotated_by = member.user.id
            img.annotated_at = datetime.now(timezone.utc)
        if is_annotated and not was_annotated:
            _bump_assignment(session, img, member.user.id)

    log_action(session, 'annotation.save', user_id=member.user.id, workspace_id=workspace_id,
               project=project, image_path=rel, detail={'boxes': len(confirmed)},
               ip=request.client.host if request.client else None)
    return {'success': True, 'is_annotated': is_annotated}


@router.post('/null')
def mark_null(workspace_id: int, project: str, request: Request, body: dict,
              member: Membership = Depends(workspace_role(*EDIT)),
              session: Session = Depends(get_session)):
    folder = _folder(session, workspace_id)
    rel = body.get('path', '')
    lbl = paths.label_path_for_image(paths.project_dir(folder, project) / rel, create_dir=True)
    write_yolo_label(lbl, [])   # empty .txt == YOLO background image (NOT missing)

    # Declaring an image empty resolves its suggestions, but KEEPS rejected ones
    # (the record of what the user turned down, so a re-run won't re-suggest).
    kept = [b for b in read_suggestions(lbl) if b.get('state') == 'rejected']
    write_suggestions(lbl, kept)

    img = _image_row(session, workspace_id, project, rel)
    if img:
        img.is_annotated = True
        img.is_null = True
        img.annotated_by = member.user.id
        img.annotated_at = datetime.now(timezone.utc)
    log_action(session, 'annotation.null', user_id=member.user.id, workspace_id=workspace_id,
               project=project, image_path=rel, ip=request.client.host if request.client else None)
    return {'success': True}


@router.delete('/null')
def unmark_null(workspace_id: int, project: str, body: dict,
                member: Membership = Depends(workspace_role(*EDIT)),
                session: Session = Depends(get_session)):
    folder = _folder(session, workspace_id)
    rel = body.get('path', '')
    lbl = paths.label_path_for_image(paths.project_dir(folder, project) / rel)
    if lbl.exists() and lbl.read_text(encoding='utf-8', errors='ignore').strip() == '':
        lbl.unlink()
    img = _image_row(session, workspace_id, project, rel)
    if img:
        img.is_annotated = False
        img.is_null = False
        img.annotated_by = None
        img.annotated_at = None
    return {'success': True}
