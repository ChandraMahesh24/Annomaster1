"""
Class management.

Each class has a permanent integer `id` that is written into YOLO .txt files.
IDs are assigned sequentially and NEVER reused when a class is deleted.
This prevents "handbag" getting the same id as a previously deleted "cat".

project.json stores:
  "classes": [
    {"id": 0, "name": "sack",     "color": [255,59,59]},
    {"id": 1, "name": "person",   "color": [255,142,30]},
    {"id": 3, "name": "dog",      "color": [74,222,128]},   ← id=2 was deleted, gap is intentional
    {"id": 5, "name": "handbag",  "color": [99,102,241]},   ← max+1, never reuses 2
  ]
"""
import re
import yaml
from pathlib import Path
from flask import Blueprint, request, jsonify, g
from app.utils.security import login_required, workspace_role_required
from app.core.storage import load_project_meta, save_project_meta, DEFAULT_PALETTE
from app.core.paths import project_dir, active_work_dir
from app.models.workspace import Workspace

classes_bp = Blueprint('classes', __name__)


def _wsf(wid):
    return Workspace.query.get_or_404(int(wid)).folder_name


def _next_class_id(classes: list) -> int:
    """Return the next safe class id — max(existing) + 1, never reuses gaps."""
    return (max(c['id'] for c in classes) + 1) if classes else 0


@classes_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/classes',
                   methods=['POST', 'DELETE'])
@login_required
@workspace_role_required('owner', 'editor')
def api_classes(workspace_id, project):
    wsf     = _wsf(workspace_id)
    data    = request.json or {}
    meta    = load_project_meta(wsf, project)
    classes = meta.get('classes', [])

    if request.method == 'POST':
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'error': 'name required'}), 400

        # Reject duplicate names
        if any(c['name'].lower() == name.lower() for c in classes):
            return jsonify({'error': f'Class "{name}" already exists'}), 409

        # Always use max+1 for new ID (never trust the client-supplied id
        # when adding via manual input — imports use _merge_classes_and_remap)
        new_id = data.get('id')
        if new_id is None or any(c['id'] == new_id for c in classes):
            new_id = _next_class_id(classes)

        color = data.get('color') or DEFAULT_PALETTE[new_id % len(DEFAULT_PALETTE)]
        classes.append({'id': new_id, 'name': name, 'color': color})
        meta['classes'] = classes
        save_project_meta(wsf, project, meta)
        return jsonify({'success': True, 'classes': classes, 'new_id': new_id})

    # DELETE — remove class AND strip its annotations from all label files
    del_id = data.get('id')
    if del_id is None:
        return jsonify({'error': 'id required'}), 400

    cls = next((c for c in classes if c['id'] == del_id), None)
    if not cls:
        return jsonify({'error': 'Class not found'}), 404

    # Remove from class list (intentional gap — do not renumber)
    meta['classes'] = [c for c in classes if c['id'] != del_id]
    save_project_meta(wsf, project, meta)

    # Scrub all label files: remove lines with this class id
    aw = active_work_dir(wsf, project)
    scrubbed_files = 0
    if aw.exists():
        for job in aw.iterdir():
            if not job.is_dir():
                continue
            lbl_dir = job / 'labels'
            if not lbl_dir.exists():
                continue
            for lbl in lbl_dir.iterdir():
                if lbl.suffix != '.txt':
                    continue
                try:
                    lines = lbl.read_text(encoding='utf-8', errors='ignore').splitlines()
                    new_lines = []
                    changed = False
                    for line in lines:
                        parts = line.strip().split()
                        if parts:
                            try:
                                if int(float(parts[0])) == del_id:
                                    changed = True
                                    continue
                            except (ValueError, IndexError):
                                pass
                        new_lines.append(line)
                    if changed:
                        if new_lines:
                            lbl.write_text('\n'.join(new_lines) + '\n', encoding='utf-8')
                        else:
                            lbl.unlink()  # no annotations left → delete file
                        scrubbed_files += 1
                except OSError:
                    pass

    return jsonify({'success': True, 'scrubbed_files': scrubbed_files})


@classes_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/classes/rename',
                   methods=['POST'])
@login_required
@workspace_role_required('owner', 'editor')
def api_classes_rename(workspace_id, project):
    wsf  = _wsf(workspace_id)
    data = request.json or {}
    meta = load_project_meta(wsf, project)
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    # Reject duplicate
    if any(c['name'].lower() == name.lower() and c['id'] != data['id']
           for c in meta.get('classes', [])):
        return jsonify({'error': f'Class "{name}" already exists'}), 409
    for c in meta.get('classes', []):
        if c['id'] == data['id']:
            c['name'] = name
    save_project_meta(wsf, project, meta)
    return jsonify({'success': True})


@classes_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/classes/color',
                   methods=['POST'])
@login_required
@workspace_role_required('owner', 'editor')
def api_classes_color(workspace_id, project):
    wsf  = _wsf(workspace_id)
    data = request.json or {}
    meta = load_project_meta(wsf, project)
    for c in meta.get('classes', []):
        if c['id'] == data['id']:
            c['color'] = data['color']
    save_project_meta(wsf, project, meta)
    return jsonify({'success': True})


@classes_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/classes/sync',
                   methods=['POST'])
@login_required
@workspace_role_required('owner', 'editor')
def api_classes_sync(workspace_id, project):
    """Write data.yaml using the class list exactly as stored (preserving sparse IDs)."""
    wsf     = _wsf(workspace_id)
    meta    = load_project_meta(wsf, project)
    classes = meta.get('classes', [])
    # Sort by id for deterministic output
    classes_sorted = sorted(classes, key=lambda c: c['id'])
    # Build names list indexed by id — fill gaps with empty string
    max_id = max((c['id'] for c in classes_sorted), default=-1)
    names  = [''] * (max_id + 1)
    for c in classes_sorted:
        names[c['id']] = c['name']
    # Remove trailing empty slots
    while names and not names[-1]:
        names.pop()

    yaml_path = project_dir(wsf, project) / 'data.yaml'
    with open(yaml_path, 'w', encoding='utf-8') as f:
        yaml.dump({'names': names, 'nc': len(classes)}, f,
                  default_flow_style=False, allow_unicode=True)
    return jsonify({'success': True, 'nc': len(classes), 'names': names})


@classes_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/classes/reindex',
                   methods=['POST'])
@login_required
@workspace_role_required('owner', 'editor')
def api_classes_reindex(workspace_id, project):
    """
    Change class IDs project-wide. Body: {"mapping": {"<old_id>": <new_id>, ...},
    "dry_run": true|false}. Dry run returns the preview (classes before/after,
    files and boxes affected) and writes nothing. Logic: core/class_reindex.py.

    Refused (409) while ANOTHER user holds a live annotation lock in this
    project: their open image still has the old IDs in memory and its autosave
    would write them back after the renumbering.
    """
    from datetime import datetime
    from app.core import class_reindex
    from app.models.annotation_lock import AnnotationLock
    data    = request.get_json(silent=True) or {}
    mapping = data.get('mapping')
    if not isinstance(mapping, dict) or not mapping:
        return jsonify({'error': 'mapping {old_id: new_id} required'}), 400
    wsf = _wsf(workspace_id)
    try:
        if data.get('dry_run'):
            return jsonify({'success': True, 'dry_run': True,
                            **class_reindex.plan(wsf, project, mapping)})
        others = AnnotationLock.query.filter(
            AnnotationLock.workspace_id == workspace_id,
            AnnotationLock.project == project,
            AnnotationLock.expires_at > datetime.utcnow(),
            AnnotationLock.locked_by != g.current_user.id,
        ).all()
        if others:
            who = sorted({(l.locker.username if l.locker else 'another user') for l in others})
            return jsonify({'error': 'Someone is annotating in this project right now ('
                            + ', '.join(who) + '). Ask them to close their images, then try again.',
                            'locked_by': who}), 409
        result = class_reindex.apply(wsf, project, mapping)
    except class_reindex.ReindexError as e:
        return jsonify({'error': str(e)}), 422
    try:
        from app.models.audit_log import log_action
        log_action('classes.reindex', user_id=g.current_user.id, workspace_id=workspace_id,
                   project=project, detail={k: result[k] for k in ('mapping', 'files', 'boxes', 'backup')},
                   ip=request.remote_addr)
    except Exception:
        pass
    return jsonify({'success': True, **result})
