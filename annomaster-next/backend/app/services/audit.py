"""
Audit logging — insert-only, and a logging failure must NEVER break the calling
request (ported rule). Every auth event, annotation save, lock force-release,
profile/assignment change goes through here.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def log_action(
    session: Session,
    action: str,
    *,
    user_id: int | None = None,
    workspace_id: int | None = None,
    project: str | None = None,
    image_path: str | None = None,
    detail: dict | None = None,
    ip: str | None = None,
) -> None:
    """
    Append one immutable audit row. Uses its OWN nested transaction so an audit
    failure rolls back only the audit insert, never the caller's work — and it
    swallows any error so the request still succeeds.
    """
    try:
        with session.begin_nested():
            session.add(AuditLog(
                user_id=user_id,
                action=action,
                workspace_id=workspace_id,
                project=project,
                image_path=image_path,
                detail=detail,
                ip_address=ip,
            ))
    except Exception:
        # Best-effort: never let the audit trail take down the real operation.
        pass
