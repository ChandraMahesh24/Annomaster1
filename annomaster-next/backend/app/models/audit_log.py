"""
AuditLog — immutable, insert-only activity history.

Unlike the operational tables, workspace_id here is ON DELETE SET NULL, not
CASCADE: an audit trail must survive the deletion of the thing it describes
(you still want the record that workspace X was deleted). It's nullable because
some events (login, register) aren't workspace-scoped. `detail` is JSON.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime, ForeignKey, Index, Integer, JSON, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AuditLog(Base):
    __tablename__ = 'audit_log'
    __table_args__ = (
        Index('ix_audit_workspace_project', 'workspace_id', 'project'),
        Index('ix_audit_action', 'action'),
        Index('ix_audit_timestamp', 'timestamp'),
    )

    id           = mapped_column(Integer, primary_key=True)
    user_id      = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    action       = mapped_column(String(80), nullable=False)
    workspace_id = mapped_column(
        ForeignKey('workspaces.id', ondelete='SET NULL'), nullable=True)
    project      = mapped_column(String(200), nullable=True)
    image_path   = mapped_column(Text, nullable=True)
    detail       = mapped_column(JSON, nullable=True)
    ip_address   = mapped_column(String(50), nullable=True)
    timestamp    = mapped_column(DateTime(timezone=True), server_default=func.now())
