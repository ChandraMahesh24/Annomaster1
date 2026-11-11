"""
Per-annotator statistics API.

Gives team owners and members a clear picture of who has contributed what:
  • images annotated per user
  • last active timestamp
  • breakdown by project or across the whole workspace

These stats are derived from the audit_log table (action = 'annotation.save')
so they are accurate without any extra counters to maintain.
"""
from flask import Blueprint, request, jsonify, g
from sqlalchemy import func
from app import db
from app.models.audit_log import AuditLog
from app.models.user import User
from app.models.workspace import WorkspaceMember
from app.utils.security import login_required, workspace_role_required

stats_bp = Blueprint('user_stats', __name__)


def _annotator_rows(workspace_id: int, project: str | None = None):
    """
    Return (user_id, annotation_count, last_active) grouped by user.
    Scoped to a workspace, optionally further narrowed to a single project.
    """
    q = (
        db.session.query(
            AuditLog.user_id,
            func.count(AuditLog.id).label('count'),
            func.max(AuditLog.timestamp).label('last_active'),
        )
        .filter(
            AuditLog.workspace_id == workspace_id,
            AuditLog.action == 'annotation.save',
            AuditLog.user_id.isnot(None),
        )
    )
    if project:
        q = q.filter(AuditLog.project == project)
    return q.group_by(AuditLog.user_id).all()


def _hydrate(rows):
    """Attach username / avatar to each stats row."""
    result = []
    for row in rows:
        user = db.session.get(User, row.user_id)
        result.append({
            'user_id':     row.user_id,
            'username':    user.username   if user else 'deleted',
            'avatar_url':  user.avatar_url if user else None,
            'count':       row.count,
            'last_active': row.last_active.isoformat() if row.last_active else None,
        })
    result.sort(key=lambda x: x['count'], reverse=True)
    return result


# ── Project-level leaderboard ─────────────────────────────────────────────────

@stats_bp.route(
    '/api/workspaces/<int:workspace_id>/projects/<project>/stats/users',
    methods=['GET'])
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def project_user_stats(workspace_id, project):
    """
    Return annotation counts per user for a single project.
    Used by the project activity panel / leaderboard widget.
    """
    rows = _annotator_rows(workspace_id, project=project)
    return jsonify({'stats': _hydrate(rows), 'project': project})


# ── Workspace-level leaderboard ───────────────────────────────────────────────

@stats_bp.route(
    '/api/workspaces/<int:workspace_id>/stats/users',
    methods=['GET'])
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def workspace_user_stats(workspace_id):
    """
    Return annotation counts per user across ALL projects in a workspace.
    Used by the workspace dashboard overview panel.
    """
    rows = _annotator_rows(workspace_id)
    return jsonify({'stats': _hydrate(rows), 'workspace_id': workspace_id})


# ── Current user's own stats (no role check needed) ──────────────────────────

@stats_bp.route(
    '/api/workspaces/<int:workspace_id>/stats/me',
    methods=['GET'])
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def my_stats(workspace_id):
    """
    Return the calling user's own contribution stats in this workspace,
    broken down by project — useful for a personal dashboard widget.
    """
    uid = g.current_user.id
    rows = (
        db.session.query(
            AuditLog.project,
            func.count(AuditLog.id).label('count'),
            func.max(AuditLog.timestamp).label('last_active'),
        )
        .filter(
            AuditLog.workspace_id == workspace_id,
            AuditLog.user_id == uid,
            AuditLog.action == 'annotation.save',
        )
        .group_by(AuditLog.project)
        .order_by(func.count(AuditLog.id).desc())
        .all()
    )
    projects = [
        {
            'project':     r.project,
            'count':       r.count,
            'last_active': r.last_active.isoformat() if r.last_active else None,
        }
        for r in rows
    ]
    total = sum(r['count'] for r in projects)
    return jsonify({
        'user_id':    uid,
        'username':   g.current_user.username,
        'avatar_url': g.current_user.avatar_url,
        'total':      total,
        'by_project': projects,
    })
