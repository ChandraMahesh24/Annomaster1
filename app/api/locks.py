"""
Annotation locking API.

Endpoints used by the frontend annotation engine to prevent two annotators
from silently overwriting each other's work on the same image.

Flow:
  1. annotate.html calls POST /acquire when the user opens an image.
  2. If another user holds a live lock → 409 response (show warning banner).
  3. If acquire succeeds → the JS sends a POST /heartbeat every 30 s to renew.
  4. On image-navigate-away or page-unload → POST /release.
  5. GET /locks (project-wide) powers the "who is editing what" dots on the
     image filmstrip.

Lock TTL is 60 s.  Locks expire automatically; the server cleans them up on
every acquire call so no background job is needed.
"""
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, g
from app import db
from app.models.annotation_lock import AnnotationLock, LOCK_TTL_SECONDS
from app.utils.security import login_required, workspace_role_required
from app.core.paths import project_dir, resolve_project_path
from app.models.workspace import Workspace

locks_bp = Blueprint('locks', __name__)


@locks_bp.before_request
def validate_lock_path():
    if request.method == 'POST':
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({'error': 'Request body must be a JSON object'}), 400
        if 'path' in data:
            ws = db.session.get(Workspace, request.view_args['workspace_id'])
            if ws:
                resolve_project_path(project_dir(ws.folder_name, request.view_args['project']), data['path'])
                data['path'] = data['path'].replace('\\', '/')


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _purge_expired(workspace_id: int, project: str):
    """Remove stale locks for this project (cheap lazy cleanup)."""
    try:
        AnnotationLock.query.filter(
            AnnotationLock.workspace_id == workspace_id,
            AnnotationLock.project == project,
            AnnotationLock.expires_at <= datetime.utcnow(),
        ).delete(synchronize_session=False)
        db.session.commit()
    except Exception:
        db.session.rollback()


def _fresh_expiry():
    return datetime.utcnow() + timedelta(seconds=LOCK_TTL_SECONDS)


# ── List all active locks for a project ───────────────────────────────────────

@locks_bp.route(
    '/api/workspaces/<int:workspace_id>/projects/<project>/locks',
    methods=['GET'])
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def list_locks(workspace_id, project):
    """Return every active (non-expired) lock for a project."""
    _purge_expired(workspace_id, project)
    locks = AnnotationLock.query.filter_by(
        workspace_id=workspace_id,
        project=project,
    ).all()
    return jsonify({'locks': [l.to_dict() for l in locks]})


# ── Acquire ───────────────────────────────────────────────────────────────────

@locks_bp.route(
    '/api/workspaces/<int:workspace_id>/projects/<project>/locks/acquire',
    methods=['POST'])
@login_required
@workspace_role_required('owner', 'editor')
def acquire_lock(workspace_id, project):
    """
    Acquire a lock for one image.

    • Own existing lock → renewed (heartbeat-style).
    • Someone else's active lock → HTTP 409 with lock details.
    • No existing lock → created.
    """
    data       = request.json or {}
    image_path = (data.get('path') or '').strip()
    if not image_path:
        return jsonify({'error': 'path required'}), 400

    _purge_expired(workspace_id, project)

    existing = AnnotationLock.query.filter_by(
        workspace_id=workspace_id,
        project=project,
        image_path=image_path,
    ).first()

    if existing:
        if existing.locked_by == g.current_user.id:
            # Renew own lock
            existing.renew()
            db.session.commit()
            return jsonify({'success': True, 'lock': existing.to_dict(), 'renewed': True})
        # Held by another user
        return jsonify({
            'success': False,
            'error':   f'@{existing.locker.username} is currently editing this image.',
            'lock':    existing.to_dict(),
        }), 409

    # ── Race window ──────────────────────────────────────────────────────
    # Between the SELECT above and this INSERT, a second annotator opening the
    # same image can slip in and insert first. The uq_lock_image UNIQUE
    # constraint guarantees only ONE of them wins at the data layer — so this
    # is never a double-lock — but the loser's commit raises IntegrityError.
    # Previously that surfaced as an unhandled 500; catch it and return the
    # same clean 409 the winner's lock would have produced, so the frontend's
    # "someone else is editing" banner fires instead of an error toast.
    from sqlalchemy.exc import IntegrityError
    lock = AnnotationLock(
        workspace_id=workspace_id,
        project=project,
        image_path=image_path,
        locked_by=g.current_user.id,
        expires_at=_fresh_expiry(),
    )
    db.session.add(lock)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        winner = AnnotationLock.query.filter_by(
            workspace_id=workspace_id, project=project, image_path=image_path,
        ).first()
        if winner and winner.locked_by == g.current_user.id:
            # Extremely rare: our own row landed via a retry. Treat as success.
            return jsonify({'success': True, 'lock': winner.to_dict()})
        if winner:
            return jsonify({
                'success': False,
                'error':   f'@{winner.locker.username} is currently editing this image.',
                'lock':    winner.to_dict(),
            }), 409
        # Row vanished again (expired between rollback and re-query) → let the
        # client retry rather than pretend success.
        return jsonify({'success': False, 'error': 'Lock contended, retry.'}), 409
    return jsonify({'success': True, 'lock': lock.to_dict()})


# ── Release ───────────────────────────────────────────────────────────────────

@locks_bp.route(
    '/api/workspaces/<int:workspace_id>/projects/<project>/locks/release',
    methods=['POST'])
@login_required
@workspace_role_required('owner', 'editor')
def release_lock(workspace_id, project):
    """Release the current user's lock on a specific image."""
    data       = request.json or {}
    image_path = (data.get('path') or '').strip()

    deleted = AnnotationLock.query.filter_by(
        workspace_id=workspace_id,
        project=project,
        image_path=image_path,
        locked_by=g.current_user.id,
    ).delete(synchronize_session=False)
    db.session.commit()
    return jsonify({'success': True, 'released': deleted > 0})


# ── Heartbeat ─────────────────────────────────────────────────────────────────

@locks_bp.route(
    '/api/workspaces/<int:workspace_id>/projects/<project>/locks/heartbeat',
    methods=['POST'])
@login_required
@workspace_role_required('owner', 'editor')
def heartbeat(workspace_id, project):
    """
    Renew TTL for all locks held by this user in this project.
    The frontend calls this every 30 s while the user has an image open.
    """
    locks = AnnotationLock.query.filter_by(
        workspace_id=workspace_id,
        project=project,
        locked_by=g.current_user.id,
    ).all()
    for lock in locks:
        lock.renew()
    db.session.commit()
    return jsonify({'success': True, 'renewed': len(locks)})


# ── Force-release (owner only) ────────────────────────────────────────────────

@locks_bp.route(
    '/api/workspaces/<int:workspace_id>/projects/<project>/locks/force-release',
    methods=['POST'])
@login_required
@workspace_role_required('owner')
def force_release(workspace_id, project):
    """Owner can break another user's lock (e.g. when they disconnect)."""
    data       = request.json or {}
    image_path = (data.get('path') or '').strip()
    if not image_path:
        return jsonify({'error': 'path required'}), 400

    deleted = AnnotationLock.query.filter_by(
        workspace_id=workspace_id,
        project=project,
        image_path=image_path,
    ).delete(synchronize_session=False)
    db.session.commit()

    try:
        from app.models.audit_log import log_action
        log_action('lock.force_release', user_id=g.current_user.id,
                   workspace_id=workspace_id, project=project,
                   image_path=image_path, ip=request.remote_addr)
    except Exception:
        pass

    return jsonify({'success': True, 'released': deleted > 0})
