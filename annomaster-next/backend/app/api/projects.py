"""
Projects, classes, and image listing.

Projects are NOT a DB table (ported decision) — a project is a directory under
`projects/` plus a project.json holding classes + settings. This router lists
them from disk, cross-referenced with per-project image counts from the DB.
Classes live in project.json (like the original), so exports/canvas read one
source.
"""
import shutil
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core import paths
from app.core.deps import Membership, workspace_role
from app.core.db import get_session
from app.models.image import Image
from app.models.user import User
from app.models.workspace import Workspace
from app.services import storage
from app.services.audit import log_action

router = APIRouter(prefix='/workspaces/{workspace_id}', tags=['projects'])

EDIT = ('owner', 'editor')
READ = ('owner', 'editor', 'viewer')


def _folder(session, workspace_id):
    ws = session.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Workspace not found')
    return ws.folder_name


def _iso(dt):
    """Serialise a naive-or-aware datetime as UTC ISO-8601 (the front-end's
    'Updated 2h ago' label parses this)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _project_activity(session, workspace_id):
    """
    Per-project counts + last-activity + contributors for one workspace, in three
    grouped queries rather than N per project — the dashboard renders every
    project at once, so a per-project loop of COUNT()s was the hot path.

    Returns {project: (total, annotated, last_activity, [{id, name}, …])}.
    """
    counts = session.execute(
        select(Image.project,
               func.count(Image.id),
               func.sum(case((Image.is_annotated.is_(True), 1), else_=0)),
               func.max(Image.uploaded_at),
               func.max(Image.annotated_at))
        .where(Image.workspace_id == workspace_id)
        .group_by(Image.project)).all()

    # Contributors = anyone who uploaded to, or annotated in, the project.
    people: dict[str, dict[int, str]] = {}
    for col in (Image.uploaded_by, Image.annotated_by):
        for project, uid, username in session.execute(
                select(Image.project, User.id, User.username)
                .join(User, User.id == col)
                .where(Image.workspace_id == workspace_id)
                .distinct()).all():
            people.setdefault(project, {})[uid] = username

    out = {}
    for project, total, ann, last_up, last_ann in counts:
        last = max((d for d in (last_up, last_ann) if d is not None), default=None)
        out[project] = (
            total or 0, int(ann or 0), last,
            [{'id': uid, 'name': name}
             for uid, name in sorted(people.get(project, {}).items())],
        )
    return out


# ── Projects ──────────────────────────────────────────────────────────────────
@router.get('/projects')
def list_projects(workspace_id: int,
                  member: Membership = Depends(workspace_role(*READ)),
                  session: Session = Depends(get_session)):
    folder = _folder(session, workspace_id)
    root = paths.workspace_projects_dir(folder)
    if not root.exists():
        return {'projects': []}
    activity = _project_activity(session, workspace_id)
    out = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        total, ann, last, people = activity.get(d.name, (0, 0, None, []))
        if last is None:
            # No images yet (or pre-provenance rows): fall back to the project
            # directory's own mtime so a fresh project still sorts sensibly.
            last = datetime.fromtimestamp(d.stat().st_mtime, tz=timezone.utc)
        out.append({'name': d.name, 'images': total, 'annotated': ann,
                    'progress': round(ann / total * 100) if total else 0,
                    'updated_at': _iso(last), 'contributors': people})
    return {'projects': out}


@router.post('/projects', status_code=201)
def create_project(workspace_id: int, body: dict, request: Request,
                   member: Membership = Depends(workspace_role(*EDIT)),
                   session: Session = Depends(get_session)):
    name = (body.get('name') or '').strip()
    if not name or '/' in name or '\\' in name or name.startswith('.'):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Invalid project name')
    folder = _folder(session, workspace_id)
    if paths.project_dir(folder, name).exists():
        raise HTTPException(status.HTTP_409_CONFLICT, 'Project already exists')
    storage.get_or_create_project(folder, name)
    log_action(session, 'project.create', user_id=member.user.id,
               workspace_id=workspace_id, project=name,
               ip=request.client.host if request.client else None)
    return {'name': name, 'images': 0, 'annotated': 0, 'progress': 0,
            'updated_at': _iso(datetime.now(timezone.utc)), 'contributors': []}


@router.delete('/projects/{project}', status_code=204)
def delete_project(workspace_id: int, project: str, request: Request,
                   member: Membership = Depends(workspace_role('owner')),
                   session: Session = Depends(get_session)):
    folder = _folder(session, workspace_id)
    for img in session.scalars(select(Image).where(
            Image.workspace_id == workspace_id, Image.project == project)):
        session.delete(img)
    d = paths.project_dir(folder, project)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    log_action(session, 'project.delete', user_id=member.user.id,
               workspace_id=workspace_id, project=project,
               ip=request.client.host if request.client else None)
    return None


# ── Classes (stored in project.json) ─────────────────────────────────────────
@router.get('/projects/{project}/classes')
def get_classes(workspace_id: int, project: str,
                member: Membership = Depends(workspace_role(*READ)),
                session: Session = Depends(get_session)):
    meta = storage.load_project_meta(_folder(session, workspace_id), project)
    return {'classes': meta.get('classes', [])}


@router.put('/projects/{project}/classes')
def set_classes(workspace_id: int, project: str, body: dict,
                member: Membership = Depends(workspace_role(*EDIT)),
                session: Session = Depends(get_session)):
    folder = _folder(session, workspace_id)
    classes = body.get('classes', [])
    if not isinstance(classes, list):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'classes must be a list')
    meta = storage.load_project_meta(folder, project)
    meta['classes'] = classes
    storage.save_project_meta(folder, project, meta)
    return {'classes': classes}


# ── Serve an image file (for the canvas) ─────────────────────────────────────
@router.get('/projects/{project}/image')
def get_image(workspace_id: int, project: str, path: str,
              member: Membership = Depends(workspace_role(*READ)),
              session: Session = Depends(get_session)):
    folder = _folder(session, workspace_id)
    pdir = paths.project_dir(folder, project).resolve()
    target = (pdir / path).resolve()
    # Path-traversal guard: the resolved file must stay under the project dir.
    if not str(target).startswith(str(pdir)) or not target.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Image not found')
    return FileResponse(target)


# ── Images (paginated) ────────────────────────────────────────────────────────
@router.get('/projects/{project}/images')
def list_images(workspace_id: int, project: str, page: int = 1, per_page: int = 50,
                batch_id: int | None = None, status: str | None = None,
                filter: str | None = None,
                member: Membership = Depends(workspace_role(*READ)),
                session: Session = Depends(get_session)):
    """
    Paginated image list. `batch_id` restricts to one upload batch (so clicking a
    batch card opens the annotator on ONLY that batch); `status` filters
    active/in_dataset; `filter` narrows by annotation state
    (annotated|unannotated|null) — the Media Library tabs. Pagination is what lets
    a large set be worked in pages of 20/50/100.
    """
    per_page = max(1, min(per_page, 500))
    base = select(Image).where(
        Image.workspace_id == workspace_id, Image.project == project)
    if batch_id is not None:
        base = base.where(Image.batch_id == batch_id)
    if status:
        base = base.where(Image.status == status)
    if filter == 'annotated':
        base = base.where(Image.is_annotated.is_(True), Image.is_null.is_(False))
    elif filter == 'unannotated':
        base = base.where(Image.is_annotated.is_(False), Image.is_null.is_(False))
    elif filter == 'null':
        base = base.where(Image.is_null.is_(True))
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = session.scalars(
        base.order_by(Image.id).offset((page - 1) * per_page).limit(per_page)).all()
    pages = (total + per_page - 1) // per_page
    return {
        'total': total, 'page': page, 'per_page': per_page, 'pages': pages,
        'images': [{'id': i.id, 'filename': i.filename, 'path': i.rel_path,
                    'is_annotated': i.is_annotated, 'is_null': i.is_null,
                    'status': i.status, 'split': i.split} for i in rows],
    }
