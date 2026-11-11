from pathlib import Path
from flask import Blueprint, request, jsonify, send_file, g
from app.utils.security import login_required, workspace_role_required
from app.core.versions import create_version, download_version_zip
from app.core.storage import load_versions, save_versions
from app.models.workspace import Workspace

versions_bp = Blueprint('versions', __name__)


def _wsf(wid): return Workspace.query.get_or_404(int(wid)).folder_name


@versions_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/versions',
                    methods=['GET', 'POST', 'DELETE'])
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def api_versions(workspace_id, project):
    wsf = _wsf(workspace_id)

    if request.method == 'GET':
        return jsonify(load_versions(wsf, project))

    if request.method == 'POST':
        if g.member_role not in ('owner', 'editor'):
            return jsonify({'error': 'Forbidden'}), 403
        data = request.json or {}
        ver  = create_version(wsf, project, data)
        return jsonify({'success': True, 'version': ver})

    # DELETE
    if g.member_role not in ('owner', 'editor'):
        return jsonify({'error': 'Forbidden'}), 403
    vid      = (request.json or {}).get('id')
    versions = load_versions(wsf, project)
    for v in versions:
        if v['id'] == vid and v.get('folder_path'):
            import shutil
            fp = Path(v['folder_path'])
            if fp.exists() and fp.is_dir():
                shutil.rmtree(fp, ignore_errors=True)
    save_versions(wsf, project, [v for v in versions if v['id'] != vid])
    return jsonify({'success': True})


@versions_bp.route(
    '/api/workspaces/<int:workspace_id>/projects/<project>/versions/<version_id>/download')
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def api_version_download(workspace_id, project, version_id):
    wsf = _wsf(workspace_id)
    buf = download_version_zip(wsf, project, version_id)
    if buf is None:
        return jsonify({'error': 'Version not found or folder missing'}), 404
    versions = load_versions(wsf, project)
    ver      = next((v for v in versions if v['id'] == version_id), {})
    safe     = ver.get('folder_name', version_id)
    return send_file(buf, mimetype='application/zip',
                     as_attachment=True, download_name=f'{safe}.zip')


@versions_bp.route(
    '/api/workspaces/<int:workspace_id>/projects/<project>/versions/<version_id>/info')
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def api_version_info(workspace_id, project, version_id):
    wsf      = _wsf(workspace_id)
    versions = load_versions(wsf, project)
    ver      = next((v for v in versions if v['id'] == version_id), None)
    if not ver:
        return jsonify({'error': 'Not found'}), 404
    folder     = Path(ver.get('folder_path', ''))
    exists     = folder.exists()
    size_mb    = 0
    file_count = 0
    if exists:
        for f in folder.rglob('*'):
            if f.is_file():
                size_mb    += f.stat().st_size
                file_count += 1
        size_mb = round(size_mb / 1024 / 1024, 1)
    return jsonify({
        'id': ver['id'], 'name': ver['name'],
        'folder_path': str(folder), 'folder_name': folder.name,
        'exists': exists, 'size_mb': size_mb, 'file_count': file_count,
    })
