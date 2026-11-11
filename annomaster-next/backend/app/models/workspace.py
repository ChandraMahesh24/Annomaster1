"""
Workspace + membership.

`public_id` (WS-XXXXXX) is also the on-disk folder name — hence UNIQUE on both
public_id and folder_name. Membership carries the owner/editor/viewer role,
enforced by a CHECK constraint (real DB-level, not app-only) and unique per
(workspace, user).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

ROLES = ('owner', 'editor', 'viewer')


class Workspace(Base):
    __tablename__ = 'workspaces'

    id          = mapped_column(Integer, primary_key=True)
    public_id   = mapped_column(String(20), unique=True, nullable=False, index=True)
    name        = mapped_column(String(200), nullable=False)
    folder_name = mapped_column(String(200), unique=True, nullable=False)  # == public_id on disk
    created_at  = mapped_column(DateTime(timezone=True), server_default=func.now())

    members = relationship(
        'WorkspaceMember', back_populates='workspace',
        cascade='all, delete-orphan',
    )


class WorkspaceMember(Base):
    __tablename__ = 'workspace_members'
    __table_args__ = (
        UniqueConstraint('workspace_id', 'user_id', name='uq_workspace_user'),
        CheckConstraint("role IN ('owner','editor','viewer')", name='ck_member_role'),
    )

    id           = mapped_column(Integer, primary_key=True)
    # Real FK with CASCADE: deleting a workspace removes its memberships. In the
    # original SQLite app workspace_id was a plain integer, which stranded rows.
    workspace_id = mapped_column(
        ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id      = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    role         = mapped_column(String(20), nullable=False, default='viewer')
    joined_at    = mapped_column(DateTime(timezone=True), server_default=func.now())

    workspace = relationship('Workspace', back_populates='members')
    user      = relationship('User')
