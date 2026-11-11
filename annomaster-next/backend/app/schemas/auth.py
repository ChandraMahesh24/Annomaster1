"""Pydantic request/response models for auth. Validation the original did by hand."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator

# EmailStr needs the optional `email_validator` package; a pragmatic regex keeps
# the port dependency-light while still rejecting obviously-bad addresses.
_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
Email = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=255)]


class _EmailValidated(BaseModel):
    email: Email

    @field_validator('email')
    @classmethod
    def _check_email(cls, v: str) -> str:
        if not _EMAIL_RE.match(v):
            raise ValueError('invalid email address')
        return v


class RegisterIn(_EmailValidated):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8, max_length=200)


class LoginIn(_EmailValidated):
    password: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=200)


class UserOut(BaseModel):
    id: int
    public_id: str
    email: str
    username: str
    avatar_url: str | None = None
    bio: str | None = None
    last_login: datetime | None = None

    model_config = {'from_attributes': True}


class TokenOut(BaseModel):
    access_token: str
    token_type: str = 'bearer'
    user: UserOut
