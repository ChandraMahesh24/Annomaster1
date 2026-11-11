"""
Assignment — owner assigns a batch to an annotator.

`done_images` is incremented ATOMICALLY on first annotation of each image
(the increment logic lands in B2 as `UPDATE … SET done_images = done_images+1`,
never read-modify-write). Auto-advances to 'submitted' at completion.
One assignment per batch (partial UNIQUE on batch_id) — the original enforced
"latest wins" by delete-then-insert; here the DB guarantees it.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

STATUSES = ('pending', 'in_progress', 'submitted', 'approved', 'rejected')


class Assignment(Base):
    __tablename__ = 'assignments'
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','in_progress','submitted','approved','rejected')",
            name='ck_assignment_status'),
        # One live assignment per batch. Partial unique: batch_id is nullable, so
        # the index only covers non-null values (many batch-less assignments OK,
        # but at most one per real batch). Enforces at the DB what the original
        # did via delete-then-insert.
        Index('uq_assignment_batch', 'batch_id', unique=True,
              postgresql_where=text('batch_id IS NOT NULL'),
              sqlite_where=text('batch_id IS NOT NULL')),
        Index('ix_assignment_workspace_project', 'workspace_id', 'project'),
    )

    id           = mapped_column(Integer, primary_key=True)
    workspace_id = mapped_column(
        ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False)
    project      = mapped_column(String(200), nullable=False)
    batch_id     = mapped_column(
        ForeignKey('upload_batches.id', ondelete='CASCADE'), nullable=True)

    assigned_to = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    assigned_by = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    assigned_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    due_date    = mapped_column(DateTime(timezone=True), nullable=True)
    note        = mapped_column(Text, nullable=True)

    status       = mapped_column(String(20), nullable=False, default='pending')
    total_images = mapped_column(Integer, nullable=False, default=0)
    done_images  = mapped_column(Integer, nullable=False, default=0)

    batch = relationship('UploadBatch', back_populates='assignments')
