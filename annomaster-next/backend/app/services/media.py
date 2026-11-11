"""
Image registration + duplicate detection.

ONE source of truth (the central `images` table), unlike the original which kept
a parallel per-project `.media_index.db` that drifted. Dedup is by MD5 within a
(workspace, project): a re-uploaded identical file is reported as a duplicate
and NOT written to disk — so there's never a file with no row (or vice versa),
the exact drift the DB audit found.
"""
import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.image import Image

ALLOWED_IMG = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp'}


def md5_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def find_duplicate(session: Session, workspace_id: int, project: str, md5: str):
    """Return an existing Image with this md5 in the same project, or None."""
    if not md5:
        return None
    return session.scalar(
        select(Image).where(
            Image.workspace_id == workspace_id,
            Image.project == project,
            Image.md5 == md5,
        )
    )


def register_image(
    session: Session, *, workspace_id: int, project: str, batch_id: int | None,
    filename: str, rel_path: str, md5: str, uploaded_by: int | None,
    is_annotated: bool = False,
) -> Image:
    """Insert one image row (caller has already checked for duplicates)."""
    from datetime import datetime, timezone
    img = Image(
        workspace_id=workspace_id, project=project, batch_id=batch_id,
        filename=filename, rel_path=rel_path, md5=md5,
        uploaded_by=uploaded_by, uploaded_at=datetime.now(timezone.utc),
        is_annotated=is_annotated,
    )
    session.add(img)
    return img
