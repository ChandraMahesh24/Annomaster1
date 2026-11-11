"""
Shared FastAPI dependencies for workspace access control.

`workspace_role(*allowed)` is THE isolation primitive: it reads `workspace_id`
from the path, confirms the current user is a member of THAT workspace with an
allowed role, and 403s otherwise. Because membership is checked by
(workspace_id, user_id), a user can never touch a workspace they don't belong
to — which is the structural guarantee behind the cross-workspace-guessing test.
Every workspace-scoped router in later phases reuses this, so isolation is
enforced in one place, not re-implemented per endpoint.
"""
from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.security import get_current_user
from app.models.user import User
from app.models.workspace import WorkspaceMember


class Membership:
    """Result of a successful role check — the user and their role here."""
    def __init__(self, user: User, workspace_id: int, role: str):
        self.user = user
        self.workspace_id = workspace_id
        self.role = role


def workspace_role(*allowed: str):
    """
    Dependency factory. Usage:
        member: Membership = Depends(workspace_role('owner', 'editor'))
    `workspace_id` is taken from the path automatically.
    """
    def dependency(
        workspace_id: int,
        user: User = Depends(get_current_user),
        session: Session = Depends(get_session),
    ) -> Membership:
        member = session.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user.id,
            )
        )
        # Non-member (or non-existent workspace) → 403. Deliberately does NOT
        # distinguish "not a member" from "workspace doesn't exist", so probing
        # foreign ids leaks nothing.
        if not member:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                'You are not a member of this workspace')
        if allowed and member.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                f'Requires role: {" or ".join(allowed)}')
        return Membership(user, workspace_id, member.role)
    return dependency
