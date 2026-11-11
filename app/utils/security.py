import jwt
import functools
from datetime import datetime, timedelta
from flask import request, jsonify, current_app, g
from app.models.user import User
from app.models.workspace import WorkspaceMember


# ── Token helpers ─────────────────────────────────────────────────────────────

def generate_token(user_id: int) -> str:
    payload = {
        'user_id': user_id,
        'exp': datetime.utcnow() + timedelta(hours=current_app.config['JWT_EXPIRY_HOURS']),
        'iat': datetime.utcnow(),
    }
    return jwt.encode(payload, current_app.config['JWT_SECRET'], algorithm='HS256')


def decode_token(token: str):
    return jwt.decode(token, current_app.config['JWT_SECRET'], algorithms=['HS256'])


def _extract_token():
    """Try Authorization header first, then cookie."""
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        t = auth_header[7:].strip()
        if t:
            return t
    return request.cookies.get('token') or None


def get_current_user():
    """
    Return the authenticated User from the JWT in the Authorization header or
    cookie.  Returns None for any invalid / expired / missing token.
    Works outside of request context (returns None instead of raising).
    """
    try:
        token = _extract_token()
        if not token:
            return None
        data    = decode_token(token)
        user_id = data.get('user_id')
        if not user_id:
            return None
        from app import db
        user = db.session.get(User, int(user_id))
        if not user or not user.is_active:
            return None
        return user
    except Exception:
        return None


# ── API decorators ────────────────────────────────────────────────────────────

def login_required(f):
    """
    Decorator: requires a valid JWT.  Sets g.current_user.
    Returns HTTP 401 if authentication fails.
    """
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Authentication required'}), 401
        if user.is_locked():
            mins = user.lockout_remaining_minutes()
            return jsonify({
                'error': f'Account temporarily locked. Try again in {mins} minute(s).'
            }), 429
        g.current_user = user
        return f(*args, **kwargs)
    return decorated


def workspace_role_required(*allowed_roles):
    """
    Decorator factory — stack AFTER @login_required (g.current_user must exist).
    Reads workspace_id from URL kwargs → JSON body → query string.
    Sets g.member_role on success.
    """
    def decorator(f):
        @functools.wraps(f)
        def decorated(*args, **kwargs):
            if not hasattr(g, 'current_user'):
                return jsonify({'error': 'Authentication required'}), 401

            workspace_id = (
                kwargs.get('workspace_id') or
                (request.json or {}).get('workspace_id') or
                request.args.get('workspace_id')
            )
            if not workspace_id:
                return jsonify({'error': 'workspace_id required'}), 400

            try:
                wid = int(workspace_id)
            except (ValueError, TypeError):
                return jsonify({'error': 'Invalid workspace_id'}), 400

            member = WorkspaceMember.query.filter_by(
                workspace_id=wid,
                user_id=g.current_user.id,
            ).first()

            if not member:
                return jsonify({'error': 'Access denied: not a workspace member'}), 403
            if member.role not in allowed_roles:
                return jsonify({
                    'error': f'Access denied: requires {" or ".join(allowed_roles)}'
                }), 403

            g.member_role = member.role
            return f(*args, **kwargs)
        return decorated
    return decorator


# ── Utility ───────────────────────────────────────────────────────────────────

def get_user_role_in_workspace(user_id: int, workspace_id: int):
    """Return role string or None if not a member."""
    member = WorkspaceMember.query.filter_by(
        workspace_id=workspace_id,
        user_id=user_id,
    ).first()
    return member.role if member else None
