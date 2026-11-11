"""UploadBatch — one row per bulk upload (drag-drop, folder, zip, video)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Integer, String, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

# Real values observed in the original DB were upload/images/folder/zip/video.
SOURCES = ('upload', 'images', 'folder', 'zip', 'video')


class UploadBatch(Base):
    __tablename__ = 'upload_batches'
    __table_args__ = (
        CheckConstraint(
            "source IN ('upload','images','folder','zip','video')",
            name='ck_batch_source'),
    )

    id           = mapped_column(Integer, primary_key=True)
    workspace_id = mapped_column(
        ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False, index=True)
    project      = mapped_column(String(200), nullable=False)
    batch_name   = mapped_column(String(200), nullable=True)
    source       = mapped_column(String(50), nullable=False, default='upload')
    uploaded_by  = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    uploaded_at  = mapped_column(DateTime(timezone=True), server_default=func.now())
    total_images = mapped_column(Integer, nullable=False, default=0)

    images      = relationship('Image', back_populates='batch')
    assignments = relationship('Assignment', back_populates='batch')
