"""
Datasets + versions + exports.

Ported rules (one note each):
  • add-to-dataset flips status + assigns split — a DB change, no file move.
  • Versions are immutable snapshots (frozen confirmed labels).
  • Export builds a ZIP (Celery job when a broker exists, else inline) in
    YOLO/COCO/VOC, reading CONFIRMED boxes only.
"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core import paths
from app.core.deps import Membership, workspace_role
from app.core.db import get_session
from app.core.yolo import parse_yolo_label
from app.models.workspace import Workspace
from app.services import datasets as ds
from app.services import exports, storage, versions
from app.services.audit import log_action

router = APIRouter(prefix='/workspaces/{workspace_id}/projects/{project}',
                   tags=['datasets'])

EDIT = ('owner', 'editor')
READ = ('owner', 'editor', 'viewer')


def _folder(session, workspace_id):
    ws = session.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Workspace not found')
    return ws.folder_name


def _class_names(folder, project):
    meta = storage.load_project_meta(folder, project)
    return [c['name'] if isinstance(c, dict) else str(c) for c in meta.get('classes', [])]


# ── Dataset membership ────────────────────────────────────────────────────────
@router.get('/dataset')
def dataset(workspace_id: int, project: str,
            member: Membership = Depends(workspace_role(*READ)),
            session: Session = Depends(get_session)):
    return ds.dataset_summary(session, workspace_id, project)


@router.post('/dataset/add')
def add_to_dataset(workspace_id: int, project: str, body: dict, request: Request,
                   member: Membership = Depends(workspace_role(*EDIT)),
                   session: Session = Depends(get_session)):
    result = ds.add_to_dataset(session, workspace_id, project,
                               ratios=body.get('ratios'), rel_paths=body.get('paths'))
    log_action(session, 'dataset.add', user_id=member.user.id, workspace_id=workspace_id,
               project=project, detail=result, ip=request.client.host if request.client else None)
    return result


@router.post('/dataset/remove')
def remove_from_dataset(workspace_id: int, project: str, body: dict,
                        member: Membership = Depends(workspace_role(*EDIT)),
                        session: Session = Depends(get_session)):
    n = ds.remove_from_dataset(session, workspace_id, project, rel_paths=body.get('paths'))
    return {'removed': n}


# ── Versions ──────────────────────────────────────────────────────────────────
@router.get('/versions')
def list_versions(workspace_id: int, project: str,
                  member: Membership = Depends(workspace_role(*READ)),
                  session: Session = Depends(get_session)):
    return {'versions': versions.list_versions(_folder(session, workspace_id), project)}


@router.post('/versions', status_code=201)
def create_version(workspace_id: int, project: str, body: dict, request: Request,
                   member: Membership = Depends(workspace_role(*EDIT)),
                   session: Session = Depends(get_session)):
    name = (body.get('name') or '').strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'version name required')
    folder = _folder(session, workspace_id)
    try:
        v = versions.create_version(session, folder, project, workspace_id,
                                    name, body.get('note', ''))
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    log_action(session, 'version.create', user_id=member.user.id, workspace_id=workspace_id,
               project=project, detail={'name': name}, ip=request.client.host if request.client else None)
    return v


# ── Export (ZIP download) ────────────────────────────────────────────────────
@router.get('/export')
def export(workspace_id: int, project: str, format: str = 'yolo',
           version: str | None = None,
           member: Membership = Depends(workspace_role(*READ)),
           session: Session = Depends(get_session)):
    if format not in exports.FORMATS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f'format must be {exports.FORMATS}')
    folder = _folder(session, workspace_id)
    pdir = paths.project_dir(folder, project)
    names = _class_names(folder, project)

    if version:
        v = versions.get_version(folder, project, version)
        if not v:
            raise HTTPException(status.HTTP_404_NOT_FOUND, 'version not found')
        items = v['manifest']                     # frozen confirmed labels
        names = v.get('classes', names)
    else:
        # live dataset: read CONFIRMED labels from each .txt (never the sidecar)
        items = []
        for img in ds.dataset_images(session, workspace_id, project):
            lbl = paths.label_path_for_image(pdir / img.rel_path)
            items.append({'rel_path': img.rel_path, 'filename': img.filename,
                          'split': img.split, 'labels': parse_yolo_label(lbl)})

    from app.workers.tasks import export_zip_service
    data = exports.build_zip(format, items, names, pdir)   # inline here; Celery task exists for prod
    fname = f'{project}_{version or "dataset"}_{format}.zip'
    return StreamingResponse(
        iter([data]), media_type='application/zip',
        headers={'Content-Disposition': f'attachment; filename="{fname}"'})
