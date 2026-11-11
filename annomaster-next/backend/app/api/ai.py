"""
Smart Detect API.

Ported rules (one note each):
  • models/ re-scanned per request; a bad .pt → 422 with a readable message.
  • Loaded YOLO instances cached by (path,mtime,size) — no per-request reload.
  • Per-project settings (model/conf/iou/mode) in project.json.
  • Predict returns RAW predictions; the suggested/confirmed/rejected
    reconciliation is client-side (canvas, C4) — same as the original.
  • Auto-Save writes ground truth with no human, so each run is audit-logged.
"""
from pathlib import Path

from fastapi import (
    APIRouter, Depends, File, HTTPException, Request, UploadFile, status,
)
from sqlalchemy.orm import Session

from app.core import paths
from app.core.deps import Membership, workspace_role
from app.core.db import get_session
from app.core.security import get_current_user
from app.models.user import User
from app.models.workspace import Workspace
from app.services import ai_models
from app.services.ai_models import ModelError
from app.services.ai_settings import read_ai_settings, write_ai_settings
from app.services.audit import log_action

# ── Global model endpoints (auth only; models are a shared asset) ─────────────
ai_router = APIRouter(prefix='/ai', tags=['smart-detect'])


@ai_router.get('/models')
def list_models(classes: bool = False, user: User = Depends(get_current_user)):
    return {'models': ai_models.list_models(with_classes=classes)}


@ai_router.get('/models/{model_name}/info')
def model_info(model_name: str, user: User = Depends(get_current_user)):
    try:
        return ai_models.describe(model_name)
    except ModelError as e:
        # 422: request is well-formed, the FILE is the problem.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail={'error': str(e), 'valid': False})


@ai_router.post('/upload_model', status_code=201)
def upload_model(file: UploadFile = File(...), user: User = Depends(get_current_user)):
    if not file.filename or not file.filename.endswith('.pt'):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Only .pt files are allowed')
    dest = ai_models.models_dir() / Path(file.filename).name    # strip dir components
    dest.write_bytes(file.file.read())
    try:
        info = ai_models.describe(dest.name)      # validate on arrival
    except ModelError as e:
        dest.unlink(missing_ok=True)              # reject unusable uploads
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    return {'success': True, **info}


# ── Project-scoped endpoints (settings, predict, audit) ──────────────────────
ai_project_router = APIRouter(
    prefix='/workspaces/{workspace_id}/projects/{project}/ai', tags=['smart-detect'])

EDIT = ('owner', 'editor')
READ = ('owner', 'editor', 'viewer')


def _folder(session, workspace_id):
    ws = session.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Workspace not found')
    return ws.folder_name


@ai_project_router.get('/settings')
def get_settings(workspace_id: int, project: str,
                 member: Membership = Depends(workspace_role(*READ)),
                 session: Session = Depends(get_session)):
    return read_ai_settings(_folder(session, workspace_id), project)


@ai_project_router.put('/settings')
def put_settings(workspace_id: int, project: str, body: dict,
                 member: Membership = Depends(workspace_role(*EDIT)),
                 session: Session = Depends(get_session)):
    try:
        return write_ai_settings(_folder(session, workspace_id), project, body)
    except ModelError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@ai_project_router.post('/predict')
def predict(workspace_id: int, project: str, body: dict,
            member: Membership = Depends(workspace_role(*EDIT)),
            session: Session = Depends(get_session)):
    folder = _folder(session, workspace_id)
    rel = body.get('path', '')
    if not rel:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'path required')
    settings = read_ai_settings(folder, project)
    model_name = body.get('model') or settings.get('model')
    if not model_name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            'No YOLO model available. Add a .pt to models/.')
    try:
        conf = float(body.get('conf', settings.get('conf', 0.45)))
    except (TypeError, ValueError):
        conf = 0.45
    conf = max(0.01, min(0.99, conf))

    img = paths.project_dir(folder, project) / rel
    if not img.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f'Image not found: {rel}')

    from app.workers.tasks import predict_service
    try:
        preds = predict_service(model_name, str(img), conf)
    except ModelError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    except Exception as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            f'Detection failed on this image: {e}')
    return {'predictions': preds, 'model': model_name, 'conf': conf}


@ai_project_router.post('/autosave_log', status_code=204)
def autosave_log(workspace_id: int, project: str, body: dict, request: Request,
                 member: Membership = Depends(workspace_role(*EDIT)),
                 session: Session = Depends(get_session)):
    # Auto-Save writes confirmed ground truth with no human review → leave a trail.
    log_action(session, 'ai.autosave', user_id=member.user.id, workspace_id=workspace_id,
               project=project, image_path=body.get('path', ''),
               detail={'model': body.get('model'), 'conf': body.get('conf'),
                       'added': body.get('added'), 'replaced': body.get('replaced')},
               ip=request.client.host if request.client else None)
    return None
