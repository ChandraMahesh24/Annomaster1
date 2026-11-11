"""
Workspace + membership endpoints.

Ported rules (one note each):
  • Creating a workspace makes the creator the OWNER and creates its on-disk
    folder (folder_name == public_id).
  • Listing returns only workspaces the caller is a member of (isolation).
  • Reads need any member role; rename/delete/invite/role-change need owner.
  • Delete removes the folder AND the DB row; FK CASCADE clears its images/
    locks/assignments/members (the orphan-row bug the SQLite app had).
"""
import shutil

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import Membership, workspace_role
from app.core.db import get_session
from app.core.ids import generate_unique_id
from app.core.paths import ensure_workspace_dir, workspace_dir
from app.core.security import get_current_user
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.schemas.workspace import (
    InviteIn, MemberOut, RoleUpdate, WorkspaceCreate, WorkspaceOut, WorkspaceRename,
)
from app.services.audit import log_action

router = APIRouter(prefix='/workspaces', tags=['workspaces'])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# ── Create ────────────────────────────────────────────────────────────────────
@router.post('', response_model=WorkspaceOut, status_code=201)
def create_workspace(body: WorkspaceCreate, request: Request,
                     user: User = Depends(get_current_user),
                     session: Session = Depends(get_session)):
    public_id = generate_unique_id(session, Workspace, 'WS')
    ws = Workspace(public_id=public_id, name=body.name.strip(), folder_name=public_id)
    session.add(ws)
    session.flush()   # need ws.id for the membership row

    session.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role='owner'))
    # Folder is created after the row flushes; if mkdir fails the whole tx rolls
    # back (get_session), so we never leave a row without a folder.
    ensure_workspace_dir(ws.folder_name)
    log_action(session, 'workspace.create', user_id=user.id, workspace_id=ws.id, ip=_ip(request))

    out = WorkspaceOut.model_validate(ws)
    out.role = 'owner'
    return out


# ── List (only the caller's workspaces) ──────────────────────────────────────
@router.get('', response_model=list[WorkspaceOut])
def list_workspaces(user: User = Depends(get_current_user),
                    session: Session = Depends(get_session)):
    rows = session.execute(
        select(Workspace, WorkspaceMember.role)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user.id)
        .order_by(Workspace.created_at.desc())
    ).all()
    result = []
    for ws, role in rows:
        o = WorkspaceOut.model_validate(ws)
        o.role = role
        result.append(o)
    return result


# ── Get one (any member) ─────────────────────────────────────────────────────
@router.get('/{workspace_id}', response_model=WorkspaceOut)
def get_workspace(workspace_id: int,
                  member: Membership = Depends(workspace_role('owner', 'editor', 'viewer')),
                  session: Session = Depends(get_session)):
    ws = session.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Workspace not found')
    o = WorkspaceOut.model_validate(ws)
    o.role = member.role
    return o


# ── Rename (owner) ────────────────────────────────────────────────────────────
@router.put('/{workspace_id}/rename', response_model=WorkspaceOut)
def rename_workspace(workspace_id: int, body: WorkspaceRename, request: Request,
                     member: Membership = Depends(workspace_role('owner')),
                     session: Session = Depends(get_session)):
    ws = session.get(Workspace, workspace_id)
    ws.name = body.name.strip()
    log_action(session, 'workspace.rename', user_id=member.user.id,
               workspace_id=workspace_id, ip=_ip(request))
    o = WorkspaceOut.model_validate(ws)
    o.role = member.role
    return o


# ── Delete (owner) — folder + cascade ────────────────────────────────────────
@router.delete('/{workspace_id}', status_code=204)
def delete_workspace(workspace_id: int, request: Request,
                     member: Membership = Depends(workspace_role('owner')),
                     session: Session = Depends(get_session)):
    ws = session.get(Workspace, workspace_id)
    folder = ws.folder_name
    log_action(session, 'workspace.delete', user_id=member.user.id,
               workspace_id=workspace_id, ip=_ip(request))
    session.delete(ws)          # FK CASCADE clears members/images/locks/assignments
    session.flush()
    # Remove files only after the DB delete is staged; if rmtree fails the tx
    # rolls back and nothing is lost.
    d = workspace_dir(folder)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    return None


# ── Members: list (any member) ───────────────────────────────────────────────
@router.get('/{workspace_id}/members', response_model=list[MemberOut])
def list_members(workspace_id: int,
                 member: Membership = Depends(workspace_role('owner', 'editor', 'viewer')),
                 session: Session = Depends(get_session)):
    rows = session.execute(
        select(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == workspace_id)
    ).all()
    return [
        MemberOut(user_id=u.id, user_public_id=u.public_id, username=u.username,
                  email=u.email, role=m.role, joined_at=m.joined_at)
        for m, u in rows
    ]


# ── Members: invite (owner) ──────────────────────────────────────────────────
@router.post('/{workspace_id}/members', response_model=MemberOut, status_code=201)
def invite_member(workspace_id: int, body: InviteIn, request: Request,
                  member: Membership = Depends(workspace_role('owner')),
                  session: Session = Depends(get_session)):
    invitee = session.scalar(select(User).where(func.lower(User.email) == body.email))
    if not invitee:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'No user with that email')
    existing = session.scalar(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == invitee.id))
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, 'User is already a member')

    m = WorkspaceMember(workspace_id=workspace_id, user_id=invitee.id, role=body.role)
    session.add(m)
    session.flush()
    log_action(session, 'member.invite', user_id=member.user.id,
               workspace_id=workspace_id, detail={'invited': invitee.public_id, 'role': body.role},
               ip=_ip(request))
    return MemberOut(user_id=invitee.id, user_public_id=invitee.public_id,
                     username=invitee.username, email=invitee.email,
                     role=m.role, joined_at=m.joined_at)


# ── Members: change role (owner) ─────────────────────────────────────────────
@router.put('/{workspace_id}/members/{user_id}/role', status_code=204)
def update_role(workspace_id: int, user_id: int, body: RoleUpdate, request: Request,
                member: Membership = Depends(workspace_role('owner')),
                session: Session = Depends(get_session)):
    target = session.scalar(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == user_id))
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Member not found')
    target.role = body.role
    log_action(session, 'member.role_change', user_id=member.user.id,
               workspace_id=workspace_id, detail={'target': user_id, 'role': body.role},
               ip=_ip(request))
    return None


# ── Members: remove (owner) ──────────────────────────────────────────────────
@router.delete('/{workspace_id}/members/{user_id}', status_code=204)
def remove_member(workspace_id: int, user_id: int, request: Request,
                  member: Membership = Depends(workspace_role('owner')),
                  session: Session = Depends(get_session)):
    if user_id == member.user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Owner cannot remove themselves')
    target = session.scalar(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == user_id))
    if target:
        session.delete(target)
        log_action(session, 'member.remove', user_id=member.user.id,
                   workspace_id=workspace_id, detail={'target': user_id}, ip=_ip(request))
    return None
