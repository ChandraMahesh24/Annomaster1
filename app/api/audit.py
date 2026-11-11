"""
Audit log read-only API.

Provides activity-feed endpoints so owners/editors can see a full history of
who did what (annotations saved, classes changed, members invited, logins, etc.)
at both workspace and project granularity.

All write operations are performed via app.models.audit_log.log_action();
this module only exposes read endpoints.
"""
from flask import Blueprint, request, jsonify
from app.models.audit_log import AuditLog
from app.utils.security import login_required, workspace_role_required

audit_bp = Blueprint('audit', __name__)

_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE     = 200


def _build_query(workspace_id, project=None):
    q = AuditLog.query.filter_by(workspace_id=workspace_id)
    if project:
        q = q.filter_by(project=project)
    action = request.args.get('action')
    if action:
        q = q.filter(AuditLog.action.like(f'{action}%'))
    user_id = request.args.get('user_id', type=int)
    if user_id:
        q = q.filter_by(user_id=user_id)
    return q.order_by(AuditLog.timestamp.desc())


def _paginate(q):
    page     = max(1, request.args.get('page', 1, type=int))
    per_page = min(
        request.args.get('per_page', _DEFAULT_PAGE_SIZE, type=int),
        _MAX_PAGE_SIZE
    )
    p = q.paginate(page=page, per_page=per_page, error_out=False)
    return {
        'logs':     [entry.to_dict() for entry in p.items],
        'total':    p.total,
        'pages':    p.pages,
        'page':     page,
        'per_page': per_page,
    }


# ── Workspace-level feed ───────────────────────────────────────────────────────

@audit_bp.route(
    '/api/workspaces/<int:workspace_id>/audit',
    methods=['GET'])
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def workspace_audit(workspace_id):
    """
    Return the audit feed for an entire workspace.

    Query params:
      page, per_page   — pagination
      action           — filter by action prefix, e.g. "annotation" or "auth.login"
      user_id          — filter by a specific team member
    """
    return jsonify(_paginate(_build_query(workspace_id)))


# ── Project-level feed ────────────────────────────────────────────────────────

@audit_bp.route(
    '/api/workspaces/<int:workspace_id>/projects/<project>/audit',
    methods=['GET'])
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def project_audit(workspace_id, project):
    """
    Return the audit feed scoped to one project.

    Same query params as workspace_audit.
    """
    return jsonify(_paginate(_build_query(workspace_id, project=project)))


# ── Summary — distinct actors in a project ────────────────────────────────────

@audit_bp.route(
    '/api/workspaces/<int:workspace_id>/projects/<project>/audit/actors',
    methods=['GET'])
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def project_actors(workspace_id, project):
    """
    Return the list of users who have performed any action in this project.
    Useful for populating filter drop-downs in the activity feed UI.
    """
    from sqlalchemy import distinct
    from app import db
    from app.models.user import User

    rows = (
        db.session.query(AuditLog.user_id)
        .filter(
            AuditLog.workspace_id == workspace_id,
            AuditLog.project == project,
            AuditLog.user_id.isnot(None),
        )
        .distinct()
        .all()
    )
    actors = []
    for (uid,) in rows:
        user = db.session.get(User, uid)
        if user:
            actors.append({
                'user_id':    uid,
                'username':   user.username,
                'avatar_url': user.avatar_url,
            })
    return jsonify({'actors': actors})
