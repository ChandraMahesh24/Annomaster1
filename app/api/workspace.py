import re
import shutil
import logging
from flask import Blueprint, request, jsonify, g
from app import db
from app.models.workspace import Workspace, WorkspaceMember
from app.models.user import User
from app.utils.security import login_required, workspace_role_required
from app.utils.id_gen import generate_unique_id
from app.core.paths import workspace_dir

workspace_bp = Blueprint('workspace', __name__)
log = logging.getLogger(__name__)


# ── Workspace CRUD ─────────────────────────────────────────────────────────────

@workspace_bp.route('/api/workspaces', methods=['GET'])
@login_required
def list_workspaces():
    memberships = g.current_user.workspace_memberships.all()
    result = []
    for m in memberships:
        ws = m.workspace
        result.append({**ws.to_dict(role=m.role),
                        'member_count': ws.members.count()})
    return jsonify(result)


@workspace_bp.route('/api/workspaces', methods=['POST'])
@login_required
def create_workspace():
    data = request.json or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    if len(name) < 3:
        return jsonify({'error': 'Workspace name must be at least 3 characters'}), 400
    if len(name) > 100:
        return jsonify({'error': 'Workspace name too long (max 100 characters)'}), 400

    # Generate unique public ID (WS-XXXXXX) — used as folder name
    public_id = generate_unique_id(Workspace, 'WS')
    folder    = public_id   # e.g. "WS-847291"

    ws = Workspace(name=name, public_id=public_id, folder_name=folder)
    db.session.add(ws)
    db.session.flush()   # gets ws.id

    member = WorkspaceMember(workspace_id=ws.id,
                              user_id=g.current_user.id,
                              role='owner')
    db.session.add(member)

    try:
        workspace_dir(folder).mkdir(parents=True, exist_ok=True)
        (workspace_dir(folder) / 'projects').mkdir(exist_ok=True)
        db.session.commit()
    except Exception:
        db.session.rollback()
        wd = workspace_dir(folder)
        if wd.exists():
            shutil.rmtree(wd)
        log.exception('Failed to create workspace %s', name)
        return jsonify({'error': 'Failed to create workspace'}), 500

    return jsonify({'success': True, 'workspace': ws.to_dict(role='owner')}), 201


@workspace_bp.route('/api/workspaces/<int:workspace_id>', methods=['DELETE'])
@login_required
@workspace_role_required('owner')
def delete_workspace(workspace_id):
    ws = Workspace.query.get_or_404(workspace_id)
    import shutil
    wd = workspace_dir(ws.folder_name)
    from app.utils.data_cleanup import clear_tracking, close_workspace_indexes
    close_workspace_indexes(ws.folder_name)
    if wd.exists():
        shutil.rmtree(wd)
    clear_tracking(workspace_id)
    db.session.delete(ws)
    db.session.commit()
    return jsonify({'success': True})



@workspace_bp.route('/api/workspaces/<int:workspace_id>/rename', methods=['PUT'])
@login_required
@workspace_role_required('owner')
def rename_workspace(workspace_id):
    data = request.json or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    ws = Workspace.query.get_or_404(workspace_id)
    ws.name = name
    db.session.commit()
    return jsonify({'success': True, 'workspace': ws.to_dict(role='owner')})


# ── Members ────────────────────────────────────────────────────────────────────

@workspace_bp.route('/api/workspaces/<int:workspace_id>/members', methods=['GET'])
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def list_members(workspace_id):
    ws = Workspace.query.get_or_404(workspace_id)
    return jsonify([m.to_dict() for m in ws.members.all()])


@workspace_bp.route('/api/workspaces/<int:workspace_id>/invite', methods=['POST'])
@login_required
@workspace_role_required('owner')
def invite_member(workspace_id):
    data  = request.json or {}
    email = (data.get('email') or '').strip().lower()
    role  = data.get('role', 'viewer')
    if role not in ('editor', 'viewer'):
        return jsonify({'error': 'role must be editor or viewer'}), 400

    invitee = User.query.filter_by(email=email).first()
    if not invitee:
        return jsonify({'error': 'No user with that email'}), 404

    existing = WorkspaceMember.query.filter_by(
        workspace_id=workspace_id, user_id=invitee.id).first()
    if existing:
        return jsonify({'error': 'User is already a member'}), 409

    m = WorkspaceMember(workspace_id=workspace_id, user_id=invitee.id, role=role)
    db.session.add(m)
    db.session.commit()
    return jsonify({'success': True, 'member': m.to_dict()}), 201


@workspace_bp.route('/api/workspaces/<int:workspace_id>/members/<int:user_id>/role',
                    methods=['PUT'])
@login_required
@workspace_role_required('owner')
def update_role(workspace_id, user_id):
    data = request.json or {}
    role = data.get('role')
    if role not in ('owner', 'editor', 'viewer'):
        return jsonify({'error': 'Invalid role'}), 400

    m = WorkspaceMember.query.filter_by(
        workspace_id=workspace_id, user_id=user_id).first()
    if not m:
        return jsonify({'error': 'Member not found'}), 404

    if user_id == g.current_user.id and role != 'owner':
        owners = WorkspaceMember.query.filter_by(
            workspace_id=workspace_id, role='owner').count()
        if owners <= 1:
            return jsonify({'error': 'Cannot demote the last owner'}), 400

    m.role = role
    db.session.commit()
    return jsonify({'success': True, 'member': m.to_dict()})


@workspace_bp.route('/api/workspaces/<int:workspace_id>/members/<int:user_id>',
                    methods=['DELETE'])
@login_required
@workspace_role_required('owner')
def remove_member(workspace_id, user_id):
    if user_id == g.current_user.id:
        return jsonify({'error': 'Cannot remove yourself'}), 400
    m = WorkspaceMember.query.filter_by(
        workspace_id=workspace_id, user_id=user_id).first()
    if not m:
        return jsonify({'error': 'Member not found'}), 404
    db.session.delete(m)
    db.session.commit()
    return jsonify({'success': True})
