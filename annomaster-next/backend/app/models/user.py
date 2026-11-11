"""User — account, auth state, profile. Referenced by most other tables."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class User(Base):
    __tablename__ = 'users'

    id            = mapped_column(Integer, primary_key=True)
    public_id     = mapped_column(String(20), unique=True, nullable=False, index=True)  # USR-XXXXXX
    email         = mapped_column(String(255), unique=True, nullable=False, index=True)
    username      = mapped_column(String(80), nullable=False)
    password_hash = mapped_column(String(255), nullable=False)

    # ── Profile ──────────────────────────────────────────────────────────────
    avatar_url = mapped_column(String(500), nullable=True)
    bio        = mapped_column(String(500), nullable=True)

    # ── Auth state (5-fail → 15-min lockout, ported in A2) ───────────────────
    is_active          = mapped_column(Boolean, nullable=False, default=True)
    failed_login_count = mapped_column(Integer, nullable=False, default=0)
    locked_until       = mapped_column(DateTime(timezone=True), nullable=True)
    last_login         = mapped_column(DateTime(timezone=True), nullable=True)

    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), onupdate=func.now())
