"""
Security primitives: password hashing, JWT, and the current-user dependency.

Ported rules:
  • Token accepted from `Authorization: Bearer` OR a `token` cookie (same dual
    source as the original app/utils/security.py).
  • JWT is HS256, `jwt_expiry_hours` from settings.

Hashing uses pbkdf2_sha256 (pure-Python, no fragile external backend) for new
hashes, but the context can still VERIFY bcrypt hashes — so old data migrates.
"""

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_session
from app.models.user import User

pwd_context = CryptContext(schemes=['pbkdf2_sha256', 'bcrypt'], deprecated='auto')


def ensure_aware(dt):
    """
    Coerce a datetime to timezone-aware UTC. Needed because SQLite drops tzinfo
    on round-trip (Postgres keeps it), so a stored `locked_until` may come back
    naive; comparing naive vs aware raises TypeError. This makes the check
    correct on both backends.
    """
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def hash_password(raw: str) -> str:
    return pwd_context.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(raw, hashed)
    except Exception:
        return False


def create_access_token(user_id: int) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        'user_id': user_id,
        'iat': now,
        'exp': now + timedelta(hours=settings.jwt_expiry_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict | None:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


def extract_token(request: Request) -> str | None:
    """
    Token from, in order: `Authorization: Bearer`, the `token` cookie, or a
    `token` query param.

    The query-param fallback exists so `<img>` / `<video>` tags can load
    auth-protected media (image thumbnails, the annotate canvas) — those tags
    cannot send an Authorization header, and cookies don't always survive the
    Vite dev proxy. Standard pattern for serving protected media to the browser.
    """
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        t = auth[7:].strip()
        if t:
            return t
    return request.cookies.get('token') or request.query_params.get('token')


def get_current_user(
    request: Request,
    session: Session = Depends(get_session),
) -> User:
    """
    FastAPI dependency → the authenticated User, or 401.

    Locked accounts are rejected here too, so a valid token issued before a
    lockout can't keep acting during it.
    """
    token = extract_token(request)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'Authentication required')
    data = decode_token(token)
    if not data or 'user_id' not in data:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'Invalid or expired token')

    user = session.get(User, int(data['user_id']))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'Account not found or inactive')
    if user.locked_until and ensure_aware(user.locked_until) > datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, 'Account temporarily locked')
    return user
