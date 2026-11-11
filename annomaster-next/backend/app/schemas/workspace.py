"""Pydantic models for workspaces + membership."""
import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class WorkspaceRename(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class WorkspaceOut(BaseModel):
    id: int
    public_id: str
    name: str
    folder_name: str
    created_at: datetime
    role: str | None = None      # the requesting user's role, filled by the endpoint

    model_config = {'from_attributes': True}


class InviteIn(BaseModel):
    email: str
    role: str = 'viewer'

    @field_validator('email')
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError('invalid email address')
        return v

    @field_validator('role')
    @classmethod
    def _role(cls, v: str) -> str:
        # owner is assigned only to the creator; invites are editor/viewer.
        if v not in ('editor', 'viewer'):
            raise ValueError('role must be editor or viewer')
        return v


class RoleUpdate(BaseModel):
    role: str

    @field_validator('role')
    @classmethod
    def _role(cls, v: str) -> str:
        if v not in ('owner', 'editor', 'viewer'):
            raise ValueError('role must be owner, editor or viewer')
        return v


class MemberOut(BaseModel):
    user_id: int
    user_public_id: str
    username: str
    email: str
    role: str
    joined_at: datetime
