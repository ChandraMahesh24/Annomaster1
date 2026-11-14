from flask import Blueprint, request, jsonify, make_response, g, render_template
from app import db, limiter
from app.models.user import User
from app.utils.security import generate_token, login_required
from app.utils.id_gen import generate_unique_id
import re

auth_bp = Blueprint('auth', __name__)


@auth_bp.before_request
def validate_auth_json():
    """Reject malformed bodies and field types before auth handlers use them."""
    if request.method not in ('POST', 'DELETE') or request.endpoint == 'auth.logout':
        return
    if request.endpoint == 'auth.delete_account' and not request.data:
        return
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Request body must be a JSON object'}), 400
    fields = ('email', 'username', 'password', 'current_password', 'new_password',
              'token', 'bio', 'avatar_url')
    if any(k in data and data[k] is not None and not isinstance(data[k], str) for k in fields):
        return jsonify({'error': 'Authentication fields must be strings'}), 400
    if request.endpoint in ('auth.register', 'auth.update_profile', 'auth.forgot_password'):
        email = (data.get('email') or '').strip()
        if email and (len(email) > 255 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email)):
            return jsonify({'error': 'Enter a valid email address (max 255 characters)'}), 400
        username = (data.get('username') or '').strip()
        if username and not 2 <= len(username) <= 100:
            return jsonify({'error': 'Username must be between 2 and 100 characters'}), 400


# ── Page routes ────────────────────────────────────────────────────────────────

@auth_bp.route('/login', methods=['GET'])
def login_page():
    return render_template('auth/login.html')


@auth_bp.route('/register', methods=['GET'])
def register_page():
    return render_template('auth/register.html')


@auth_bp.route('/forgot-password', methods=['GET'])
def forgot_password_page():
    # One template, two states: ?token=… shows "choose a new password".
    return render_template('auth/forgot_password.html', token=request.args.get('token', ''))


@auth_bp.route('/help', methods=['GET'])
def help_page():
    return render_template('pages/help.html')


# ── Register ───────────────────────────────────────────────────────────────────

@auth_bp.route('/api/auth/register', methods=['POST'])
@limiter.limit("10 per hour")
def register():
    data     = request.json or {}
    email    = (data.get('email') or '').strip().lower()
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    if not email or not username or not password:
        return jsonify({'error': 'email, username and password are required'}), 400
    if len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400
    if len(username) < 2:
        return jsonify({'error': 'Username must be at least 2 characters'}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'Email already registered'}), 409
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Username already taken'}), 409

    # Generate unique public ID (USR-XXXXXX)
    public_id = generate_unique_id(User, 'USR')

    user = User(email=email, username=username, public_id=public_id)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    _audit('auth.register', user_id=user.id)

    token = generate_token(user.id)
    resp  = make_response(jsonify({'success': True, 'user': user.to_dict(), 'token': token}))
    resp.set_cookie('token', token, httponly=True, samesite='Lax', max_age=86400 * 7)
    return resp, 201


# ── Login ──────────────────────────────────────────────────────────────────────

@auth_bp.route('/api/auth/login', methods=['POST'])
@limiter.limit("15 per minute; 60 per hour")   # brute-force guard
def login():
    data     = request.json or {}
    email    = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400

    user = User.query.filter_by(email=email).first()

    # ── Account lockout check ─────────────────────────────────────────────────
    if user and user.is_locked():
        mins = user.lockout_remaining_minutes()
        _audit('auth.login_locked', user_id=user.id)
        return jsonify({
            'error': f'Account locked after too many failed attempts. '
                     f'Try again in {mins} minute(s).'
        }), 429

    # ── Credential check ──────────────────────────────────────────────────────
    if not user or not user.check_password(password):
        if user:
            user.record_failed_login()
            db.session.commit()
            if user.is_locked():
                _audit('auth.login_failed_lockout', user_id=user.id)
                return jsonify({
                    'error': f'Too many failed attempts. Account locked for '
                             f'{user.lockout_remaining_minutes()} minute(s).'
                }), 429
        _audit('auth.login_failed')
        return jsonify({'error': 'Invalid email or password'}), 401

    if not user.is_active:
        return jsonify({'error': 'Account disabled. Contact your administrator.'}), 403

    # ── Success ───────────────────────────────────────────────────────────────
    user.record_successful_login()
    db.session.commit()
    _audit('auth.login', user_id=user.id)

    token = generate_token(user.id)
    resp  = make_response(jsonify({'success': True, 'user': user.to_dict(), 'token': token}))
    resp.set_cookie('token', token, httponly=True, samesite='Lax', max_age=86400 * 7)
    return resp


# ── Logout ────────────────────────────────────────────────────────────────────

@auth_bp.route('/api/auth/logout', methods=['POST'])
def logout():
    resp = make_response(jsonify({'success': True}))
    resp.delete_cookie('token')
    return resp


# ── Current user ──────────────────────────────────────────────────────────────

@auth_bp.route('/api/auth/me', methods=['GET'])
@login_required
def me():
    return jsonify(g.current_user.to_dict())


# ── Profile update ────────────────────────────────────────────────────────────

@auth_bp.route('/api/auth/update-profile', methods=['POST'])
@login_required
def update_profile():
    """Change username, email, bio and/or avatar_url."""
    data      = request.json or {}
    username  = (data.get('username') or '').strip()
    email     = (data.get('email') or '').strip().lower()
    bio       = data.get('bio')
    avatar_url = data.get('avatar_url')
    user      = g.current_user

    if username and username != user.username:
        if len(username) < 2:
            return jsonify({'error': 'Username must be at least 2 characters'}), 400
        if User.query.filter_by(username=username).first():
            return jsonify({'error': 'Username already taken'}), 409
        user.username = username

    if email and email != user.email:
        if User.query.filter_by(email=email).first():
            return jsonify({'error': 'Email already registered'}), 409
        user.email = email

    if bio is not None:
        user.bio = bio[:500]

    if avatar_url is not None:
        user.avatar_url = avatar_url[:500] if avatar_url else None

    db.session.commit()
    _audit('auth.profile_update', user_id=user.id)
    return jsonify({'success': True, 'user': user.to_dict()})


# ── Password change ───────────────────────────────────────────────────────────

@auth_bp.route('/api/auth/change-password', methods=['POST'])
@login_required
@limiter.limit("5 per hour")
def change_password():
    """Change password — requires current password for verification."""
    data         = request.json or {}
    current_pass = data.get('current_password') or ''
    new_pass     = data.get('new_password') or ''
    user         = g.current_user

    if not current_pass or not new_pass:
        return jsonify({'error': 'current_password and new_password required'}), 400
    if len(new_pass) < 8:
        return jsonify({'error': 'New password must be at least 8 characters'}), 400
    if not user.check_password(current_pass):
        return jsonify({'error': 'Current password is incorrect'}), 401

    user.set_password(new_pass)
    db.session.commit()
    _audit('auth.password_change', user_id=user.id)

    token = generate_token(user.id)
    resp  = make_response(jsonify({'success': True, 'token': token}))
    resp.set_cookie('token', token, httponly=True, samesite='Lax', max_age=86400 * 7)
    return resp


# ── Forgot / reset password ───────────────────────────────────────────────────

@auth_bp.route('/api/auth/forgot-password', methods=['POST'])
@limiter.limit("5 per hour")
def forgot_password():
    """Send a reset link. Always answers the same way, so it can't be used
    to discover which emails have accounts."""
    from flask import current_app
    from app.core import password_reset

    email = ((request.json or {}).get('email') or '').strip().lower()
    if not email:
        return jsonify({'error': 'Email is required'}), 400

    # Check service configuration before looking up an account. The same error
    # for every address avoids exposing membership or falsely claiming delivery.
    if not current_app.config.get('MAIL_SERVER') or not (
        current_app.config.get('MAIL_FROM') or current_app.config.get('MAIL_USERNAME')
    ):
        return jsonify({
            'error': 'Password reset email is unavailable. The administrator must configure the email service. Please contact your administrator.',
            'code': 'mail_not_configured',
        }), 503

    user = User.query.filter_by(email=email).first()
    if user and user.is_active:
        base = (current_app.config.get('APP_BASE_URL') or request.host_url).rstrip('/')
        link = f"{base}/forgot-password?token={password_reset.make_token(user)}"
        password_reset.send_reset_link(user, link)
        _audit('auth.password_reset_requested', user_id=user.id)

    return jsonify({
        'success': True,
        'message': 'If an account exists for that email, a reset link is on its way.',
        'expires_minutes': password_reset.token_minutes(),
    })


@auth_bp.route('/api/auth/reset-password/check', methods=['POST'])
@limiter.limit("30 per hour")
def reset_password_check():
    """Let the page tell an expired/used link apart before the user types."""
    from app.core import password_reset
    token = (request.json or {}).get('token') or ''
    return jsonify({'valid': bool(token and password_reset.verify_token(token))})


@auth_bp.route('/api/auth/reset-password', methods=['POST'])
@limiter.limit("10 per hour")
def reset_password():
    from app.core import password_reset

    data     = request.json or {}
    token    = data.get('token') or ''
    new_pass = data.get('password') or ''

    if len(new_pass) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400
    user = password_reset.verify_token(token) if token else None
    if not user:
        return jsonify({'error': 'This reset link is invalid or has expired. Request a new one.'}), 400

    user.set_password(new_pass)          # also invalidates this token (single use)
    user.failed_login_count = 0          # a verified owner shouldn't stay locked out
    user.locked_until       = None
    db.session.commit()
    _audit('auth.password_reset', user_id=user.id)
    return jsonify({'success': True})


# ── Delete account ────────────────────────────────────────────────────────────

@auth_bp.route('/api/auth/delete-account', methods=['DELETE'])
@login_required
def delete_account():
    """Permanently delete own account. Sole-owner workspaces are also deleted."""
    from app.models.workspace import Workspace, WorkspaceMember
    import shutil
    from flask import current_app
    from pathlib import Path

    user = g.current_user

    memberships = user.workspace_memberships.all()
    for m in memberships:
        if m.role == 'owner':
            ws = m.workspace
            other_owners = WorkspaceMember.query.filter_by(
                workspace_id=ws.id, role='owner').filter(
                WorkspaceMember.user_id != user.id).count()
            if other_owners == 0:
                from app.utils.data_cleanup import clear_tracking, close_workspace_indexes
                close_workspace_indexes(ws.folder_name)
                ws_path = Path(current_app.config['WORKSPACE_ROOT']) / ws.folder_name
                if ws_path.exists():
                    shutil.rmtree(ws_path)
                clear_tracking(ws.id)
                db.session.delete(ws)

    _audit('auth.account_delete', user_id=user.id)
    db.session.delete(user)
    db.session.commit()

    resp = make_response(jsonify({'success': True}))
    resp.delete_cookie('token')
    return resp


# ── Internal helper ───────────────────────────────────────────────────────────

def _audit(action: str, user_id: int | None = None):
    try:
        from app.models.audit_log import log_action
        log_action(action, user_id=user_id, ip=request.remote_addr)
    except Exception:
        pass
