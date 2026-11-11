"""
Auth endpoints — register / login / logout / me / change-password.

Ported rules (one note each):
  • JWT returned in body AND set as an httpOnly `token` cookie (dual source).
  • 5 consecutive failed logins → 15-minute lockout, auto-cleared on next success.
  • Rate limits via dependencies (login 15/min·60/hr, register 10/hr, pw 5/hr).
  • Every auth event is audit-logged; audit failure never breaks the request.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.ids import generate_unique_id
from app.core.ratelimit import login_limit, pwchange_limit, register_limit
from app.core.security import (
    create_access_token, ensure_aware, get_current_user, hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordIn, LoginIn, RegisterIn, TokenOut, UserOut,
)
from app.services.audit import log_action

router = APIRouter(prefix='/auth', tags=['auth'])

MAX_FAILS = 5
LOCKOUT_MINUTES = 15


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _set_cookie(response: Response, token: str) -> None:
    # httpOnly so JS can't read it; the JWT still also comes back in the body
    # for clients that prefer the Authorization header.
    response.set_cookie(
        'token', token, httponly=True, samesite='lax', max_age=60 * 60 * 24)


def _issue(response: Response, user: User) -> TokenOut:
    token = create_access_token(user.id)
    _set_cookie(response, token)
    return TokenOut(access_token=token, user=UserOut.model_validate(user))


@router.post('/register', response_model=TokenOut, status_code=201,
             dependencies=[Depends(register_limit)])
def register(body: RegisterIn, request: Request, response: Response,
             session: Session = Depends(get_session)):
    # Rule: unique email (case-insensitive), like the original.
    email = body.email.lower()
    exists = session.scalar(select(User).where(func.lower(User.email) == email))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, 'Email already registered')

    user = User(
        public_id=generate_unique_id(session, User, 'USR'),
        email=email,
        username=body.username.strip(),
        password_hash=hash_password(body.password),
    )
    session.add(user)
    session.flush()   # assign user.id before we log / issue a token
    log_action(session, 'auth.register', user_id=user.id, ip=request.client.host if request.client else None)
    return _issue(response, user)


@router.post('/login', response_model=TokenOut,
             dependencies=[Depends(login_limit)])
def login(body: LoginIn, request: Request, response: Response,
          session: Session = Depends(get_session)):
    ip = request.client.host if request.client else None
    user = session.scalar(select(User).where(func.lower(User.email) == body.email.lower()))

    # Rule: locked account is rejected before any password check.
    locked_until = ensure_aware(user.locked_until) if user else None
    if user and locked_until and locked_until > _utcnow():
        mins = int((locked_until - _utcnow()).total_seconds() // 60) + 1
        log_action(session, 'auth.login_locked', user_id=user.id, ip=ip)
        # Commit the audit row before raising: get_session rolls back on any
        # raised exception (correct for most 4xx), but here the side effect must
        # survive the 429 — otherwise the trail of lockout hits is lost.
        session.commit()
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f'Account locked. Try again in {mins} minute(s).')

    if not user or not verify_password(body.password, user.password_hash):
        # Rule: count consecutive fails; 5th trips the lockout. Matches the
        # original app/models/user.py::record_failed_login EXACTLY — the count
        # is NOT reset when locking, so after the 15-min lock expires the very
        # next failure (count 5→6, still ≥ MAX) re-locks immediately. Only a
        # SUCCESSFUL login clears the counter (below).
        if user:
            user.failed_login_count = (user.failed_login_count or 0) + 1
            if user.failed_login_count >= MAX_FAILS:
                user.locked_until = _utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
            log_action(session, 'auth.login_fail', user_id=user.id, ip=ip)
            # Persist the incremented counter + audit BEFORE the 401. Without
            # this the rollback-on-exception in get_session would discard the
            # increment and the counter would never reach the lockout threshold.
            session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'Invalid email or password')

    # Rule: success clears the counter and any lock, records last_login.
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login = _utcnow()
    log_action(session, 'auth.login', user_id=user.id, ip=ip)
    return _issue(response, user)


@router.post('/logout', status_code=204)
def logout(response: Response):
    response.delete_cookie('token')
    return Response(status_code=204)


@router.get('/me', response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)


@router.post('/change-password', status_code=204,
             dependencies=[Depends(pwchange_limit)])
def change_password(body: ChangePasswordIn, request: Request,
                    user: User = Depends(get_current_user),
                    session: Session = Depends(get_session)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Current password is incorrect')
    # Re-fetch in this session to persist the change.
    db_user = session.get(User, user.id)
    db_user.password_hash = hash_password(body.new_password)
    log_action(session, 'auth.password_change', user_id=user.id,
               ip=request.client.host if request.client else None)
    return Response(status_code=204)
