"""
Lock helpers — TTL enforced on EVERY read.

The original's bug was checking expiry only at acquire, so a stale lock could
block saves for other users until someone next tried to acquire. Here
`active_lock` filters by `expires_at > now`, so a lock past its 60s TTL is
treated as absent by every reader (save conflict check, GET annotations, lock
list) — not just at acquire time.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.security import ensure_aware
from app.models.annotation_lock import AnnotationLock

TTL_SECONDS = 60


def now() -> datetime:
    return datetime.now(timezone.utc)


def fresh_expiry() -> datetime:
    return now() + timedelta(seconds=TTL_SECONDS)


def is_expired(lock: AnnotationLock) -> bool:
    return ensure_aware(lock.expires_at) <= now()


def purge_expired(session: Session, workspace_id: int, project: str) -> None:
    session.execute(
        delete(AnnotationLock).where(
            AnnotationLock.workspace_id == workspace_id,
            AnnotationLock.project == project,
            AnnotationLock.expires_at <= now(),
        )
    )


def active_lock(session: Session, workspace_id: int, project: str, image_path: str):
    """Return the live (non-expired) lock for an image, or None."""
    lock = session.scalar(select(AnnotationLock).where(
        AnnotationLock.workspace_id == workspace_id,
        AnnotationLock.project == project,
        AnnotationLock.image_path == image_path))
    if lock and is_expired(lock):
        return None                 # TTL enforced on read
    return lock
