import io
import os
from flask import Blueprint, request, jsonify, send_file, g, abort
from PIL import Image
from app import db
from app.utils.security import login_required, workspace_role_required
from app.core.projects import (list_projects, get_or_create_project,
                                delete_project, get_project_summary,
                                rename_project, duplicate_project,
                                move_project, merge_project, ProjectOpError)
from app.core.storage import load_project_meta
from app.core.paths import project_dir
from app.models.annotation_lock import AnnotationLock
from app.models.assignment import Assignment
from app.models.audit_log import AuditLog
from app.models.image import Image as ImageRow
from app.models.upload_batch import UploadBatch
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember

projects_bp = Blueprint('projects', __name__)


def _wsf(workspace_id):
    return Workspace.query.get_or_404(int(workspace_id)).folder_name


def _contributors(workspace_id):
    """
    {project: [{id, name}, …]} — everyone who uploaded to, or annotated in,
    each project of one workspace. Two grouped queries for the whole workspace
    rather than a pair per project, since the dashboard renders them all at once.

    Annotations live on disk, but *provenance* is in the DB (Image.uploaded_by /
    annotated_by), which is why this can't come from core/projects.py — that
    module is deliberately Flask/DB-free.
    """
    out = {}
    for col in (ImageRow.uploaded_by, ImageRow.annotated_by):
        rows = (ImageRow.query
                .with_entities(ImageRow.project, User.id, User.username)
                .join(User, User.id == col)
                .filter(ImageRow.workspace_id == workspace_id)
                .distinct().all())
        for project, uid, username in rows:
            out.setdefault(project, {})[uid] = username
    return {p: [{'id': uid, 'name': n} for uid, n in sorted(people.items())]
            for p, people in out.items()}


@projects_bp.route('/api/workspaces/<int:workspace_id>/projects', methods=['GET'])
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def api_list_projects(workspace_id):
    wsf      = _wsf(workspace_id)
    projects = list_projects(wsf)
    people   = _contributors(workspace_id)
    result   = []
    for name, meta in projects.items():
        s = get_project_summary(wsf, name)
        result.append({**s, 'classes': meta.get('classes', []),
                       'contributors': people.get(name, [])})
    return jsonify(result)


@projects_bp.route('/api/workspaces/<int:workspace_id>/projects', methods=['POST'])
@login_required
@workspace_role_required('owner', 'editor')
def api_create_project(workspace_id):
    data = request.json or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Name required'}), 400
    wsf = _wsf(workspace_id)
    if project_dir(wsf, name).exists():
        return jsonify({'error': f'Project "{name}" already exists'}), 409
    # Pass creator user ID so project.json records who made it
    get_or_create_project(wsf, name, created_by_id=g.current_user.id)
    summary = get_project_summary(wsf, name)
    return jsonify({'success': True, 'project': summary}), 201


@projects_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>',
                   methods=['DELETE'])
@login_required
@workspace_role_required('owner')
def api_delete_project(workspace_id, project):
    wsf = _wsf(workspace_id)
    try:
        delete_project(wsf, project)
    except ProjectOpError as e:
        # A locked file now surfaces as a readable 400 instead of a bare 500.
        return _op_error(e)
    from app.utils.data_cleanup import clear_tracking
    clear_tracking(workspace_id, project)
    db.session.commit()
    return jsonify({'success': True})


@projects_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/cover',
                   methods=['GET', 'POST'])
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def api_project_cover(workspace_id, project):
    wsf   = _wsf(workspace_id)
    pd    = project_dir(wsf, project)
    cover = pd / 'cover.jpg'

    if request.method == 'POST':
        if g.member_role not in ('owner', 'editor'):
            return jsonify({'error': 'Forbidden'}), 403
        f = request.files.get('file')
        if not f:
            return jsonify({'error': 'No file'}), 400
        try:
            raw = f.read()
            if not raw:
                return jsonify({'error': 'Empty file'}), 400
            img = Image.open(io.BytesIO(raw)).convert('RGB')
            img.thumbnail((640, 400))
            pd.mkdir(parents=True, exist_ok=True)
            img.save(str(cover), 'JPEG', quality=90)
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    if cover.exists():
        resp = send_file(cover, mimetype='image/jpeg')
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return resp
    abort(404)


@projects_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/cover-from-path',
                   methods=['POST'])
@login_required
@workspace_role_required('owner', 'editor')
def api_cover_from_path(workspace_id, project):
    data = request.json or {}
    rel  = (data.get('path') or '').strip()
    if not rel:
        return jsonify({'error': 'path required'}), 400
    wsf      = _wsf(workspace_id)
    pd       = project_dir(wsf, project)
    from app.core.paths import resolve_project_path
    src_path = resolve_project_path(pd, rel)
    if not src_path.exists():
        return jsonify({'error': 'Image not found'}), 404
    cover = pd / 'cover.jpg'
    try:
        img = Image.open(str(src_path)).convert('RGB')
        img.thumbnail((640, 400))
        img.save(str(cover), 'JPEG', quality=90)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@projects_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/tags')
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def api_project_tags(workspace_id, project):
    """Every distinct tag in the project — drives the filter dropdowns and the
    add-tag suggestions, so users reuse a tag instead of creating a near-copy."""
    from app.core import tags as tags_mod
    return jsonify({'tags': tags_mod.all_tags(_wsf(workspace_id), project)})


# ══ Project operations: rename · duplicate · move · merge ═════════════════════
# Each moves real directories AND the DB rows that name the project. Five tables
# carry a `project` string (images, upload_batches, assignments,
# annotation_locks, audit_log); miss one and the project's images vanish from
# the UI while still sitting on disk.

_PROJECT_TABLES = (ImageRow, UploadBatch, Assignment, AnnotationLock, AuditLog)


def _retarget_rows(workspace_id, project, *, new_project=None,
                   new_workspace_id=None):
    """Point every project-scoped row at a new project name and/or workspace."""
    patch = {}
    if new_project is not None:
        patch['project'] = new_project
    if new_workspace_id is not None:
        patch['workspace_id'] = new_workspace_id
    if not patch:
        return
    for model in _PROJECT_TABLES:
        (model.query
         .filter(model.workspace_id == workspace_id, model.project == project)
         .update(patch, synchronize_session=False))


def _op_error(exc):
    return jsonify({'error': str(exc)}), 400


@projects_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/rename',
                   methods=['PUT'])
@login_required
@workspace_role_required('owner', 'editor')
def api_rename_project(workspace_id, project):
    wsf  = _wsf(workspace_id)
    name = (request.json or {}).get('name')
    try:
        new = rename_project(wsf, project, name)
    except ProjectOpError as e:
        return _op_error(e)
    _retarget_rows(workspace_id, project, new_project=new)
    db.session.commit()
    return jsonify({'success': True, 'name': new,
                    'project': get_project_summary(wsf, new)})


@projects_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/duplicate',
                   methods=['POST'])
@login_required
@workspace_role_required('owner', 'editor')
def api_duplicate_project(workspace_id, project):
    wsf  = _wsf(workspace_id)
    name = (request.json or {}).get('name') or f'{project}-copy'
    try:
        new = duplicate_project(wsf, project, name)
    except ProjectOpError as e:
        return _op_error(e)

    # Clone the batches first so the copied images can point at the copies —
    # sharing batch rows would make "delete the original" strip the duplicate's
    # provenance too.
    batch_map = {}
    for b in UploadBatch.query.filter_by(workspace_id=workspace_id,
                                         project=project).all():
        nb = UploadBatch(workspace_id=workspace_id, project=new,
                         batch_name=b.batch_name, source=b.source,
                         uploaded_by=b.uploaded_by, uploaded_at=b.uploaded_at,
                         total_images=b.total_images)
        db.session.add(nb)
        db.session.flush()
        batch_map[b.id] = nb.id

    for img in ImageRow.query.filter_by(workspace_id=workspace_id,
                                        project=project).all():
        db.session.add(ImageRow(
            workspace_id=workspace_id, project=new,
            batch_id=batch_map.get(img.batch_id),
            filename=img.filename, rel_path=img.rel_path,
            status=img.status, split=img.split,
            is_annotated=img.is_annotated, is_null=img.is_null,
            uploaded_by=img.uploaded_by, uploaded_at=img.uploaded_at,
            annotated_by=img.annotated_by, annotated_at=img.annotated_at,
            reviewed_by=img.reviewed_by, reviewed_at=img.reviewed_at,
            added_to_dataset_at=img.added_to_dataset_at,
            assigned_to=img.assigned_to))

    db.session.commit()
    return jsonify({'success': True, 'name': new,
                    'project': get_project_summary(wsf, new)}), 201


@projects_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/move',
                   methods=['POST'])
@login_required
@workspace_role_required('owner')
def api_move_project(workspace_id, project):
    data      = request.json or {}
    target_id = data.get('target_workspace_id')
    if not target_id:
        return jsonify({'error': 'target_workspace_id required'}), 400
    target_id = int(target_id)

    # The mover must be able to WRITE in the destination too, otherwise this
    # is a way to push a project into a workspace you only read.
    member = WorkspaceMember.query.filter_by(
        workspace_id=target_id, user_id=g.current_user.id).first()
    if not member or member.role not in ('owner', 'editor'):
        return jsonify({'error': 'You need edit access to the target workspace'}), 403

    src_wsf = _wsf(workspace_id)
    dst_wsf = _wsf(target_id)
    try:
        new = move_project(src_wsf, project, dst_wsf, data.get('name'))
    except ProjectOpError as e:
        return _op_error(e)
    _retarget_rows(workspace_id, project,
                   new_project=new, new_workspace_id=target_id)
    db.session.commit()
    return jsonify({'success': True, 'name': new, 'workspace_id': target_id})


@projects_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/merge',
                   methods=['POST'])
@login_required
@workspace_role_required('owner')
def api_merge_project(workspace_id, project):
    """Merge `project` INTO `target`, then delete `project`. Class indices in
    every moved label file are remapped onto the target's class list."""
    wsf    = _wsf(workspace_id)
    target = ((request.json or {}).get('target') or '').strip()
    if not target:
        return jsonify({'error': 'target project required'}), 400
    try:
        result = merge_project(wsf, project, target)
    except ProjectOpError as e:
        return _op_error(e)

    # Job folders renamed on collision must be reflected in rel_path, which
    # embeds the job name (Active_Work/<job>/images/<file>).
    rows = ImageRow.query.filter_by(workspace_id=workspace_id,
                                    project=project).all()
    for img in rows:
        for old_job, new_job in result['renamed_jobs'].items():
            if f'/{old_job}/' in img.rel_path.replace(os.sep, '/'):
                img.rel_path = img.rel_path.replace(old_job, new_job)
                break
    _retarget_rows(workspace_id, project, new_project=target)
    db.session.commit()
    return jsonify({'success': True, 'target': target, **result,
                    'project': get_project_summary(wsf, target)})
