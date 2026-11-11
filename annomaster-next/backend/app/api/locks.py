"""
Annotation locking — prevents two annotators silently overwriting the same image.

Ported rules (one note each):
  • 60s TTL, heartbeat renews; expiry enforced on EVERY read (services/locks).
  • acquire → 409 with who holds it; own lock → renewed.
  • acquire race is caught: the UNIQUE(ws,project,path) constraint means only one
    winner; the loser gets a clean 409, not a 500 (the DB-audit fix, ported).
  • owner can force-release; force-release is audited.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import Membership, workspace_role
from app.core.db import get_session
from app.models.annotation_lock import AnnotationLock
from app.services import locks as lock_svc
from app.services.audit import log_action

router = APIRouter(prefix='/workspaces/{workspace_id}/projects/{project}/locks',
                   tags=['locks'])

EDIT = ('owner', 'editor')
READ = ('owner', 'editor', 'viewer')


@router.get('')
def list_locks(workspace_id: int, project: str,
               member: Membership = Depends(workspace_role(*READ)),
               session: Session = Depends(get_session)):
    lock_svc.purge_expired(session, workspace_id, project)
    rows = session.scalars(select(AnnotationLock).where(
        AnnotationLock.workspace_id == workspace_id,
        AnnotationLock.project == project)).all()
    # Filter again on read in case any slipped the purge window.
    return {'locks': [l.to_dict() for l in rows if not lock_svc.is_expired(l)]}


@router.post('/acquire')
def acquire(workspace_id: int, project: str, body: dict,
            member: Membership = Depends(workspace_role(*EDIT)),
            session: Session = Depends(get_session)):
    image_path = (body.get('path') or '').strip()
    if not image_path:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'path required')

    lock_svc.purge_expired(session, workspace_id, project)
    existing = lock_svc.active_lock(session, workspace_id, project, image_path)
    if existing:
        if existing.locked_by == member.user.id:
            existing.expires_at = lock_svc.fresh_expiry()   # renew own
            return {'success': True, 'lock': existing.to_dict(), 'renewed': True}
        return _conflict(existing)

    lock = AnnotationLock(workspace_id=workspace_id, project=project,
                          image_path=image_path, locked_by=member.user.id,
                          expires_at=lock_svc.fresh_expiry())
    session.add(lock)
    try:
        session.flush()
    except IntegrityError:
        # Lost the race to another concurrent acquire → return the winner's 409
        # instead of a 500 (the UNIQUE constraint guaranteed only one winner).
        session.rollback()
        winner = lock_svc.active_lock(session, workspace_id, project, image_path)
        if winner and winner.locked_by == member.user.id:
            return {'success': True, 'lock': winner.to_dict()}
        if winner:
            return _conflict(winner)
        raise HTTPException(status.HTTP_409_CONFLICT, 'Lock contended, retry')
    return {'success': True, 'lock': lock.to_dict()}


def _conflict(lock: AnnotationLock):
    raise HTTPException(
        status.HTTP_409_CONFLICT,
        detail={'error': f'@{lock.locker.username if lock.locker else "someone"} '
                         'is editing this image', 'lock': lock.to_dict()})


@router.post('/release')
def release(workspace_id: int, project: str, body: dict,
            member: Membership = Depends(workspace_role(*EDIT)),
            session: Session = Depends(get_session)):
    image_path = (body.get('path') or '').strip()
    n = session.execute(delete(AnnotationLock).where(
        AnnotationLock.workspace_id == workspace_id,
        AnnotationLock.project == project,
        AnnotationLock.image_path == image_path,
        AnnotationLock.locked_by == member.user.id)).rowcount
    return {'success': True, 'released': n > 0}


@router.post('/heartbeat')
def heartbeat(workspace_id: int, project: str,
              member: Membership = Depends(workspace_role(*EDIT)),
              session: Session = Depends(get_session)):
    rows = session.scalars(select(AnnotationLock).where(
        AnnotationLock.workspace_id == workspace_id,
        AnnotationLock.project == project,
        AnnotationLock.locked_by == member.user.id)).all()
    for lock in rows:
        lock.expires_at = lock_svc.fresh_expiry()
    return {'success': True, 'renewed': len(rows)}


@router.post('/force-release')
def force_release(workspace_id: int, project: str, body: dict, request: Request,
                  member: Membership = Depends(workspace_role('owner')),
                  session: Session = Depends(get_session)):
    image_path = (body.get('path') or '').strip()
    if not image_path:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'path required')
    n = session.execute(delete(AnnotationLock).where(
        AnnotationLock.workspace_id == workspace_id,
        AnnotationLock.project == project,
        AnnotationLock.image_path == image_path)).rowcount
    log_action(session, 'lock.force_release', user_id=member.user.id,
               workspace_id=workspace_id, project=project, image_path=image_path,
               ip=request.client.host if request.client else None)
    return {'success': True, 'released': n > 0}
