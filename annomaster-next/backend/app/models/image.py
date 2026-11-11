"""
Image — one row per image file. Metadata only; the file + its YOLO .txt live on
disk and NEVER move. Lifecycle (active → in_dataset, split) is a column change.

NOTE on `split`: Section 1 of the port spec summarises it as train|val|test, but
the actual original behaviour (disk dirs Completed_Datasets/{train,valid,test}
and the live DB) uses **train|valid|test**. Parity means matching behaviour, not
the summary — so the CHECK uses 'valid'. Flagged in PORT_PLAN.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

STATUSES = ('active', 'in_dataset')
SPLITS   = ('train', 'valid', 'test')


class Image(Base):
    __tablename__ = 'images'
    __table_args__ = (
        CheckConstraint("status IN ('active','in_dataset')", name='ck_image_status'),
        CheckConstraint(
            "split IS NULL OR split IN ('train','valid','test')",
            name='ck_image_split'),
        Index('ix_image_workspace_project', 'workspace_id', 'project'),
        Index('ix_image_status', 'status'),
    )

    id           = mapped_column(Integer, primary_key=True)
    workspace_id = mapped_column(
        ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False)
    project      = mapped_column(String(200), nullable=False)
    batch_id     = mapped_column(
        ForeignKey('upload_batches.id', ondelete='SET NULL'), nullable=True, index=True)

    filename = mapped_column(String(500), nullable=False)
    rel_path = mapped_column(Text, nullable=False)   # relative to project dir; never changes
    # MD5 of file content for duplicate detection. In the SQLite app this lived
    # in a SEPARATE per-project index DB that drifted from the central table;
    # here it's one column on the single source of truth.
    md5 = mapped_column(String(32), nullable=True, index=True)

    # ── Lifecycle (column changes, never a file move) ────────────────────────
    status = mapped_column(String(20), nullable=False, default='active')
    split  = mapped_column(String(10), nullable=True)

    # ── Annotation state (is_null still needs an empty .txt on disk) ─────────
    is_annotated = mapped_column(Boolean, nullable=False, default=False)
    is_null      = mapped_column(Boolean, nullable=False, default=False)

    # ── Provenance ───────────────────────────────────────────────────────────
    uploaded_by = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    uploaded_at = mapped_column(DateTime(timezone=True), nullable=True)
    annotated_by = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    annotated_at = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by  = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    reviewed_at  = mapped_column(DateTime(timezone=True), nullable=True)
    added_to_dataset_at = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_to  = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    batch = relationship('UploadBatch', back_populates='images')
