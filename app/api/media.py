import math
from flask import Blueprint, request, jsonify, send_file, abort, g
from app.utils.security import login_required, workspace_role_required
from app.core.media import get_or_make_thumbnail, ALLOWED_IMG, _ensure_index
from app.core.yolo import is_valid_annotation_file, parse_yolo_label
from app.core.paths import project_dir, label_path_for_image, resolve_project_path
from app.core.storage import load_project_meta
from app.models.workspace import Workspace

media_bp = Blueprint('media', __name__)


def _wsf(workspace_id):
    return Workspace.query.get_or_404(int(workspace_id)).folder_name


@media_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/media')
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def api_media(workspace_id, project):
    wsf      = _wsf(workspace_id)
    page     = max(1, int(request.args.get('page', 1)))
    per_page = max(10, min(200, int(request.args.get('per_page', 50))))
    meta     = load_project_meta(wsf, project)

    pd = project_dir(wsf, project)
    _ensure_index(wsf, project)

    # ── Fast path: SQLite query ───────────────────────────────────────────────
    try:
        from app.core import db_index
        result     = db_index.get_media_page(pd, page, per_page)
        total      = result['total']
        total_pages = max(1, math.ceil(total / per_page))
        page        = min(page, total_pages)

        from app.models.image import Image as ImageModel
        split_map = {row.rel_path.replace('\\', '/'): row.split for row in ImageModel.query.filter_by(workspace_id=workspace_id, project=project).all() if row.split}
        for item in result['media']:
            value = split_map.get(item['path'].replace('\\', '/'))
            if value:
                item['split'] = 'valid' if value == 'val' else value
        return jsonify({
            'media':      result['media'],
            'annotated':  result['annotated'],
            'null_paths': result['null_paths'],
            'classes':    meta.get('classes', []),
            'pagination': {
                'page': page, 'per_page': per_page,
                'total': total, 'total_pages': total_pages,
                'has_prev': page > 1, 'has_next': page < total_pages,
            },
        })
    except Exception:
        pass

    # ── Fallback: filesystem scan ─────────────────────────────────────────────
    from app.core.media import collect_media
    all_media   = collect_media(wsf, project)
    total       = len(all_media)
    total_pages = max(1, math.ceil(total / per_page))
    page        = min(page, total_pages)
    start       = (page - 1) * per_page
    page_media  = all_media[start:start + per_page]

    annotated_on_page = []
    for item in page_media:
        lbl = label_path_for_image(pd / item['path'], create_dir=False)
        if is_valid_annotation_file(lbl):
            annotated_on_page.append(item['path'])

    return jsonify({
        'media':      page_media,
        'annotated':  annotated_on_page,
        'null_paths': [],
        'classes':    meta.get('classes', []),
        'pagination': {
            'page': page, 'per_page': per_page,
            'total': total, 'total_pages': total_pages,
            'has_prev': page > 1, 'has_next': page < total_pages,
        },
    })


@media_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/media/count')
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def api_media_count(workspace_id, project):
    wsf = _wsf(workspace_id)
    pd  = project_dir(wsf, project)
    _ensure_index(wsf, project)
    try:
        from app.core import db_index
        counts = db_index.get_counts(pd)
        return jsonify({'total': counts['total'], 'annotated': counts['annotated']})
    except Exception:
        from app.core.media import collect_media, annotated_paths
        return jsonify({
            'total':     len(collect_media(wsf, project)),
            'annotated': len(annotated_paths(wsf, project)),
        })


@media_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/image')
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def api_image(workspace_id, project):
    wsf  = _wsf(workspace_id)
    rel  = request.args.get('path', '')
    full = resolve_project_path(project_dir(wsf, project), rel)
    if not full.is_file():
        abort(404)
    return send_file(full, mimetype='image/jpeg')


@media_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/thumbnail')
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def api_thumbnail(workspace_id, project):
    wsf  = _wsf(workspace_id)
    rel  = request.args.get('path', '')
    pd   = project_dir(wsf, project)
    full = resolve_project_path(pd, rel)
    if not full.is_file():
        abort(404)
    cache_root = pd / '.thumbs'
    try:
        cache = get_or_make_thumbnail(full, cache_root)
        return send_file(cache, mimetype='image/jpeg')
    except Exception:
        abort(500)


@media_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/stats')
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def api_stats(workspace_id, project):
    wsf     = _wsf(workspace_id)
    meta    = load_project_meta(wsf, project)
    classes = meta.get('classes', [])
    pd      = project_dir(wsf, project)
    _ensure_index(wsf, project)

    try:
        from app.core import db_index
        counts = db_index.get_counts(pd)
        total      = counts['total']
        annotated_ = counts['annotated']
    except Exception:
        from app.core.media import collect_media, annotated_paths
        total      = len(collect_media(wsf, project))
        annotated_ = len(annotated_paths(wsf, project))

    # Class-level counts still require reading label files
    from app.core.media import collect_media
    # 'id' is required: the Classes page keys its counts by class id (it was
    # missing, so every class showed 0 annotations / 0 images).
    cls_counts = {c['id']: {'id': c['id'], 'count': 0, 'images': 0,
                             'name': c['name'], 'color': c['color']}
                  for c in classes}
    total_boxes = 0
    labelled = 0      # images with >= 1 box (annotated_images = reviewed/"Done")
    for m in collect_media(wsf, project):
        lbl = label_path_for_image(pd / m['path'], create_dir=False)
        if lbl.exists():
            boxes   = parse_yolo_label(lbl)
            if boxes:
                labelled += 1
            img_ids = set()
            for b in boxes:
                cid = b['class_id']
                if cid in cls_counts:
                    cls_counts[cid]['count'] += 1
                    img_ids.add(cid)
                total_boxes += 1
            for cid in img_ids:
                if cid in cls_counts:
                    cls_counts[cid]['images'] += 1

    return jsonify({
        'total_images':     total,
        'annotated_images': annotated_,
        'total_boxes':      total_boxes,
        'labelled_images':  labelled,
        'class_counts':     list(cls_counts.values()),
        'splits': {},
    })
