"""
AnnotationLock — one active lock per image (60s TTL, heartbeat-renewed).

UNIQUE(workspace_id, project, image_path) is the data-layer guarantee that two
annotators can't both hold the same image — the app-level check races, the
constraint doesn't. TTL expiry is enforced on every READ in B2 (a bug in the
original was checking it only at acquire).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class AnnotationLock(Base):
    __tablename__ = 'annotation_locks'
    __table_args__ = (
        UniqueConstraint('workspace_id', 'project', 'image_path', name='uq_lock_image'),
        Index('ix_lock_expires', 'expires_at'),
        Index('ix_lock_workspace_project', 'workspace_id', 'project'),
    )

    id           = mapped_column(Integer, primary_key=True)
    workspace_id = mapped_column(
        ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False)
    project      = mapped_column(String(200), nullable=False)
    image_path   = mapped_column(Text, nullable=False)
    locked_by    = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    acquired_at  = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at   = mapped_column(DateTime(timezone=True), nullable=False)

    locker = relationship('User')

    def to_dict(self) -> dict:
        return {
            'locked_by': self.locked_by,
            'username': self.locker.username if self.locker else None,
            'image_path': self.image_path,
            'acquired_at': self.acquired_at.isoformat() if self.acquired_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
        }
