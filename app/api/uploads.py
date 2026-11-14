import yaml
import zipfile
from datetime import datetime
from pathlib import Path
from flask import Blueprint, request, jsonify, g
from app.utils.security import login_required, workspace_role_required
from app.core.storage import (load_uploads, save_uploads, load_project_meta,
                               save_project_meta, next_upload_id, DEFAULT_PALETTE)
from app.core.paths import (batch_img_dir, batch_lbl_dir, batch_job_dir,
                             active_work_dir)
from app.core.projects import get_or_create_project
from app.core.media import ALLOWED_IMG
from app.core.yolo import (is_valid_annotation_file, merge_classes_and_remap,
                            remap_label_file)
from app.models.workspace import Workspace


def _safe_filename(filename: str, max_len: int = 100) -> str:
    """
    Sanitize and truncate filename to prevent Windows MAX_PATH issues.
    Keeps the extension. Replaces spaces and special chars with underscores.
    """
    import re
    p    = Path(filename)
    stem = p.stem
    ext  = p.suffix  # e.g. ".jpg"
    # Replace problematic characters
    stem = re.sub(r'[^\w\-.]', '_', stem)
    # Truncate stem so total filename <= max_len
    max_stem = max_len - len(ext)
    if len(stem) > max_stem:
        stem = stem[:max_stem]
    return stem + ext


# Both helpers moved to app/core/yolo.py so project-merge can reuse them (the
# API layer must not be imported from core). Re-exported under their original
# private names so every call site in this file is unchanged.
_merge_classes_and_remap = merge_classes_and_remap
_remap_label_file        = remap_label_file




uploads_bp = Blueprint('uploads', __name__)


def _wsf(wid): return Workspace.query.get_or_404(int(wid)).folder_name


def _new_job_name():
    now = datetime.now()
    return now.strftime('job_%Y-%m-%d_%H-%M-%S_') + f'{now.microsecond // 1000:03d}'


def _register_images(wsf, project, workspace_id, uploader_id, batch, dest_paths):
    """
    Register a list of freshly-written image files in BOTH DB mirrors:
    the per-project `.media_index.db` (drives the UI) and the central
    `images` table (metadata).

    This is the single registration step the other upload paths already do
    inline. It exists as a helper mainly so `extract_frames` — which wrote
    files to disk but registered them NOWHERE, stranding every extracted
    frame as a file with no DB row in either mirror — can share it.

    Registration failures are LOGGED, not silently swallowed. The prior
    `except: pass` on every DB write is exactly what let this drift build up
    invisibly; a warning in the log is the minimum needed to notice it.

    Returns the count actually registered in the central table.
    """
    from app import db
    from app.core.paths import project_dir as _pd_fn
    from app.core import db_index
    from app.models.image import Image as ImageModel
    from app.core.yolo import is_valid_annotation_file
    from app.core.paths import label_path_for_image
    from app.utils.logger import get_logger

    log = get_logger(__name__)
    pd = _pd_fn(wsf, project)
    registered = 0

    for dest in dest_paths:
        try:
            idx_res = db_index.add_image(pd, dest, batch['job_name'], keep_duplicate=True)
        except Exception as e:
            log.warning('media-index register failed for %s: %s', dest.name, e)
            continue
        if idx_res.get('duplicate'):
            continue
        try:
            lbl = label_path_for_image(dest, create_dir=False)
            has_ann = is_valid_annotation_file(lbl)
            db.session.add(ImageModel(
                workspace_id=workspace_id,
                project=project,
                batch_id=batch.get('batch_db_id'),
                filename=dest.name,
                rel_path=idx_res['path'],
                uploaded_by=uploader_id,
                is_annotated=has_ann,
            ))
            registered += 1
        except Exception as e:
            log.warning('images-table register failed for %s: %s', dest.name, e)

    if registered:
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            log.warning('images-table commit failed (%d rows): %s', registered, e)
            registered = 0
    return registered


def _create_batch(wsf, project, source='images', workspace_id=None, uploader_id=None):
    get_or_create_project(wsf, project)
    uid      = next_upload_id(wsf, project)
    job_name = _new_job_name()
    batch_img_dir(wsf, project, job_name).mkdir(parents=True, exist_ok=True)
    batch_lbl_dir(wsf, project, job_name).mkdir(parents=True, exist_ok=True)

    # Create UploadBatch row in the main DB
    batch_db_id = None
    if workspace_id:
        try:
            from app import db
            from app.models.upload_batch import UploadBatch
            ub = UploadBatch(
                workspace_id=workspace_id,
                project=project,
                batch_name=job_name,
                source=source,
                uploaded_by=uploader_id,
            )
            db.session.add(ub)
            db.session.commit()
            batch_db_id = ub.id
        except Exception:
            pass

    batch = {
        'upload_id': uid, 'job_name': job_name,
        'datetime_str': job_name, 'source': source,
        'cls_names': [], 'in_dataset': False,
        'uploaded_at': datetime.now().isoformat(),
        'uploaded_by': uploader_id,
        'batch_db_id': batch_db_id,
    }
    batches = load_uploads(wsf, project)
    batches.append(batch)
    save_uploads(wsf, project, batches)
    return batch


def _count_batch(wsf, project, job_name):
    img_dir = batch_img_dir(wsf, project, job_name)
    lbl_dir = batch_lbl_dir(wsf, project, job_name)
    if not img_dir.exists():
        return {'total': 0, 'annotated': 0, 'unannotated': 0, 'null_count': 0, 'pending': 0}
    imgs  = [f for f in img_dir.iterdir() if f.suffix.lower() in ALLOWED_IMG]
    total = len(imgs)
    annotated = null_count = 0
    for img in imgs:
        lbl = lbl_dir / (img.stem + '.txt')
        if lbl.exists():
            c = lbl.read_text(encoding='utf-8', errors='ignore').strip()
            if c == '' or c == '__null__':   # empty file = YOLO background image
                null_count += 1
            elif is_valid_annotation_file(lbl):
                annotated += 1
    return {'total': total, 'annotated': annotated,
            'unannotated': total - annotated - null_count,
            'null_count': null_count,
            'pending': total - annotated - null_count}


def _get_batch_extra(b, workspace_id):
    """Resolve uploader username and current assignment for a batch dict."""
    extra = {'uploader_name': None, 'assignment': None}
    try:
        from app.models.user import User
        uid = b.get('uploaded_by')
        if uid:
            u = User.query.get(int(uid))
            extra['uploader_name'] = u.username if u else None
        batch_db_id = b.get('batch_db_id')
        if batch_db_id:
            from app.models.assignment import Assignment
            a = (Assignment.query
                 .filter_by(batch_id=batch_db_id)
                 .order_by(Assignment.assigned_at.desc())
                 .first())
            extra['assignment'] = a.to_dict() if a else None
    except Exception:
        pass
    return extra


@uploads_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/upload',
                   methods=['POST'])
@login_required
@workspace_role_required('owner', 'editor')
def api_upload(workspace_id, project):
    wsf       = _wsf(workspace_id)
    upload_id = request.form.get('upload_id')
    file      = request.files.get('file')
    if not file:
        return jsonify({'error': 'No file'}), 400
    get_or_create_project(wsf, project)

    uid_kwargs = dict(workspace_id=workspace_id, uploader_id=g.current_user.id)

    # Re-use existing batch if upload_id provided — avoids reloading _uploads.json
    if upload_id:
        batches = load_uploads(wsf, project)
        batch   = next((b for b in batches if str(b['upload_id']) == str(upload_id)), None)
        if not batch:
            batch = _create_batch(wsf, project, 'images', **uid_kwargs)
    else:
        batch = _create_batch(wsf, project, 'images', **uid_kwargs)

    img_dir = batch_img_dir(wsf, project, batch['job_name'])
    img_dir.mkdir(parents=True, exist_ok=True)

    # Save directly to disk — no PIL processing, no memory buffering
    fname = _safe_filename(Path(file.filename).name)
    dest  = img_dir / fname
    if dest.exists():
        stem_s, ext_s = Path(fname).stem, Path(fname).suffix
        counter = 2
        while dest.exists():
            dest = img_dir / f'{stem_s}_{counter}{ext_s}'
            counter += 1
    file.save(str(dest))

    # Register in SQLite index — enables fast media queries + duplicate detection
    from app.core.paths import project_dir as _pd
    from app.core import db_index
    pd  = _pd(wsf, project)
    result = db_index.add_image(pd, dest, batch['job_name'], keep_duplicate=True)
    if result.get('duplicate'):
        # Keep the file in this new batch — do not delete.
        # The hashes table already has the MD5 so we skip re-registering,
        # but the file must stay on disk so _count_batch finds it.
        pass

    # Register in main images table
    try:
        from app import db
        from app.models.image import Image as ImageModel
        db.session.add(ImageModel(
            workspace_id=workspace_id,
            project=project,
            batch_id=batch.get('batch_db_id'),
            filename=dest.name,
            rel_path=result['path'],
            uploaded_by=g.current_user.id,
        ))
        db.session.commit()
    except Exception:
        pass

    return jsonify({'success': True, 'upload_id': batch['upload_id'],
                    'job_name': batch['job_name']})


@uploads_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/upload/folder',
                   methods=['POST'])
@login_required
@workspace_role_required('owner', 'editor')
def api_upload_folder(workspace_id, project):
    wsf       = _wsf(workspace_id)
    upload_id = request.form.get('upload_id')
    files     = request.files.getlist('files')
    get_or_create_project(wsf, project)

    uid_kwargs = dict(workspace_id=workspace_id, uploader_id=g.current_user.id)

    if upload_id:
        batches = load_uploads(wsf, project)
        batch   = next((b for b in batches if str(b['upload_id']) == str(upload_id)), None)
        if not batch:
            batch = _create_batch(wsf, project, 'folder', **uid_kwargs)
    else:
        batch = _create_batch(wsf, project, 'folder', **uid_kwargs)

    img_dir = batch_img_dir(wsf, project, batch['job_name'])
    lbl_dir = batch_lbl_dir(wsf, project, batch['job_name'])
    img_dir.mkdir(parents=True, exist_ok=True)
    lbl_dir.mkdir(parents=True, exist_ok=True)

    cls_names = []
    for f in files:
        nm = Path(f.filename).name
        if nm in ('data.yaml', 'data.yml'):
            try:
                cls_names = yaml.safe_load(f.read()).get('names', [])
                f.seek(0)
            except Exception:
                pass
        elif nm == 'classes.txt':
            cls_names = [l.strip() for l in f.read().decode(errors='ignore').splitlines() if l.strip()]
            f.seek(0)

    # Merge incoming class names, get remap dict: source_idx → project_id
    remap = _merge_classes_and_remap(wsf, project, cls_names) if cls_names else {}

    img_files, lbl_files = {}, {}
    for f in files:
        nm  = Path(f.filename).name
        ext = Path(nm).suffix.lower()
        st  = Path(nm).stem
        if ext in ALLOWED_IMG:
            img_files[st] = f
        elif ext == '.txt' and nm not in ('classes.txt',):
            lbl_files[st] = f

    from app.core.paths import project_dir as _pd_fn
    from app.core import db_index as _dbi
    _pd = _pd_fn(wsf, project)

    saved = annotated = 0
    new_image_rows = []
    for stem, img_f in img_files.items():
        nm   = _safe_filename(Path(img_f.filename).name)
        dest = img_dir / nm
        img_f.save(dest)
        saved += 1
        # Register in SQLite index (best-effort)
        idx_result = None
        try: idx_result = _dbi.add_image(_pd, dest, batch['job_name'], keep_duplicate=True)
        except Exception: pass
        lbl_stem   = Path(img_f.filename).stem
        has_label  = False
        if lbl_stem in lbl_files or stem in lbl_files:
            lbl_f = lbl_files.get(lbl_stem) or lbl_files.get(stem)
            lbl_f.seek(0)
            data = lbl_f.read()
            lbl_dest = lbl_dir / (Path(nm).stem + '.txt')
            lbl_dest.write_bytes(data)
            if remap:
                _remap_label_file(lbl_dest, remap)
            if data.strip():
                annotated += 1
                has_label = True
        if idx_result and not idx_result.get('duplicate'):
            new_image_rows.append({
                'filename': dest.name,
                'rel_path': idx_result['path'],
                'is_annotated': has_label,
            })

    # Bulk-register in main images table
    try:
        from app import db
        from app.models.image import Image as ImageModel
        for row in new_image_rows:
            db.session.add(ImageModel(
                workspace_id=workspace_id,
                project=project,
                batch_id=batch.get('batch_db_id'),
                filename=row['filename'],
                rel_path=row['rel_path'],
                uploaded_by=g.current_user.id,
                is_annotated=row['is_annotated'],
            ))
        db.session.commit()
    except Exception:
        pass

    batches = load_uploads(wsf, project)
    for b in batches:
        if b['upload_id'] == batch['upload_id']:
            b['cls_names'] = cls_names
            b['source']    = 'folder'
    save_uploads(wsf, project, batches)

    meta = load_project_meta(wsf, project)
    return jsonify({
        'success': True, 'upload_id': batch['upload_id'],
        'job_name': batch['job_name'], 'total_images': saved,
        'annotated': annotated, 'unannotated': saved - annotated,
        'cls_names': cls_names, 'classes': meta.get('classes', []),
    })


@uploads_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/upload/create_batch',
                   methods=['POST'])
@login_required
@workspace_role_required('owner', 'editor')
def api_create_batch(workspace_id, project):
    wsf    = _wsf(workspace_id)
    data   = request.json or {}
    source = data.get('source', 'images')
    get_or_create_project(wsf, project)
    batch = _create_batch(wsf, project, source,
                          workspace_id=workspace_id, uploader_id=g.current_user.id)
    return jsonify({'success': True, 'batch': batch})


@uploads_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/uploads')
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def api_uploads(workspace_id, project):
    wsf     = _wsf(workspace_id)
    batches = load_uploads(wsf, project)
    aw      = active_work_dir(wsf, project)
    result  = []
    for b in batches:
        jd = aw / b.get('job_name', '')
        if not jd.exists():
            continue
        counts = _count_batch(wsf, project, b['job_name'])
        # Always include the batch if the job folder exists.
        # Even if total=0 (all images were moved to dataset), keep showing it
        # until the user explicitly deletes it.
        result.append({**b, **counts, **_get_batch_extra(b, workspace_id)})
    return jsonify(result)


@uploads_bp.route(
    '/api/workspaces/<int:workspace_id>/projects/<project>/uploads/<int:uid>/tags',
    methods=['PUT'])
@login_required
@workspace_role_required('owner', 'editor')
def api_set_batch_tags(workspace_id, project, uid):
    """Replace a batch's tags. Tags live in the batch record itself, so they
    move and delete with the batch."""
    from app.core import tags as tags_mod
    cleaned = tags_mod.set_batch_tags(_wsf(workspace_id), project, uid,
                                      (request.json or {}).get('tags'))
    if cleaned is None:
        return jsonify({'error': 'Batch not found'}), 404
    return jsonify({'success': True, 'tags': cleaned})


@uploads_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/uploads/<int:uid>',
                   methods=['DELETE'])
@login_required
@workspace_role_required('owner', 'editor')
def api_delete_upload(workspace_id, project, uid):
    import shutil
    wsf     = _wsf(workspace_id)
    batches = load_uploads(wsf, project)
    batch   = next((b for b in batches if b['upload_id'] == uid), None)
    if batch:
        jd = batch_job_dir(wsf, project, batch['job_name'])
        if jd.exists():
            shutil.rmtree(jd)
        # Remove all images for this job from the SQLite index
        try:
            from app.core import db_index
            from app.core.paths import project_dir as _pd3
            db_index.remove_job(_pd3(wsf, project), batch['job_name'])
        except Exception:
            pass
        save_uploads(wsf, project, [b for b in batches if b['upload_id'] != uid])
    return jsonify({'success': True})


@uploads_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/uploads/<int:uid>/media')
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def api_batch_media(workspace_id, project, uid):
    wsf     = _wsf(workspace_id)
    batches = load_uploads(wsf, project)
    batch   = next((b for b in batches if b['upload_id'] == uid), None)
    if not batch:
        return jsonify({'error': 'Not found'}), 404

    from app.core.paths import project_dir
    pd      = project_dir(wsf, project)
    img_dir = batch_img_dir(wsf, project, batch['job_name'])
    lbl_dir = batch_lbl_dir(wsf, project, batch['job_name'])
    media, ann, null_paths = [], [], []
    if not img_dir.exists():
        meta = load_project_meta(wsf, project)
        return jsonify({'media': [], 'annotated': [], 'null_paths': [],
                        'classes': meta.get('classes', [])})
    for img in sorted(img_dir.iterdir()):
        if img.suffix.lower() not in ALLOWED_IMG:
            continue
        rel = str(img.relative_to(pd))
        lbl = lbl_dir / (img.stem + '.txt')
        media.append({'path': rel, 'name': img.name,
                      'job': batch['job_name'], 'split': None})
        if is_valid_annotation_file(lbl):
            ann.append(rel)
        elif lbl.is_file() and lbl.read_text(encoding='utf-8', errors='ignore').strip() in ('', '__null__'):
            null_paths.append(rel)

    meta = load_project_meta(wsf, project)
    return jsonify({'media': media, 'annotated': ann,
                    'null_paths': null_paths, 'classes': meta.get('classes', [])})


@uploads_bp.route(
    '/api/workspaces/<int:workspace_id>/projects/<project>/uploads/<int:uid>/add_to_dataset',
    methods=['POST'])
@login_required
@workspace_role_required('owner', 'editor')
def api_add_to_dataset(workspace_id, project, uid):
    wsf  = _wsf(workspace_id)
    data = request.json or {}
    from app.core.datasets import add_batch_to_dataset
    result = add_batch_to_dataset(
        wsf, project, uid,
        train_r=float(data.get('train', 0.70)),
        val_r=float(data.get('val', 0.15)),
        test_r=float(data.get('test', 0.15)),
        workspace_id=workspace_id,
        reviewer_id=g.current_user.id,
    )
    if result is None:
        return jsonify({'error': 'Batch not found — check upload_id'}), 404
    # Return error with 200 so JS gets the message (not a network error)
    return jsonify(result)


@uploads_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/import/preview',
                   methods=['POST'])
@login_required
@workspace_role_required('owner', 'editor')
def api_import_preview(workspace_id, project):
    file = request.files.get('file')
    if not file:
        return jsonify({'error': 'No file'}), 400
    total_imgs = total_lbls = 0
    cls_names  = []
    has_yaml   = False
    splits     = {}
    warnings   = []
    try:
        with zipfile.ZipFile(file) as zf:
            for n in zf.namelist():
                p   = Path(n)
                ext = p.suffix.lower()
                if ext in ALLOWED_IMG:
                    total_imgs += 1
                    for part in p.parts:
                        lp = part.lower()
                        if lp in ('train', 'valid', 'val', 'test', 'validation'):
                            sp = 'valid' if lp in ('val', 'validation') else lp
                            splits.setdefault(sp, {'images': 0, 'matched': 0})
                            splits[sp]['images'] += 1
                elif ext == '.txt' and p.name != 'classes.txt':
                    total_lbls += 1
                elif p.name in ('data.yaml', 'data.yml'):
                    has_yaml = True
                    with zf.open(n) as f:
                        try:
                            cls_names = yaml.safe_load(f.read()).get('names', [])
                        except Exception:
                            pass
        if not total_imgs:
            warnings.append('No images found in ZIP')
        return jsonify({
            'success': True, 'total_images': total_imgs,
            'total_labels': total_lbls, 'cls_names': cls_names,
            'has_yaml': has_yaml, 'is_yolo_dataset': bool(splits),
            'splits': splits, 'warnings': warnings,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@uploads_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/import',
                   methods=['POST'])
@login_required
@workspace_role_required('owner', 'editor')
def api_import(workspace_id, project):
    wsf  = _wsf(workspace_id)
    file = request.files.get('file')
    if not file:
        return jsonify({'error': 'No file'}), 400
    get_or_create_project(wsf, project)
    batch   = _create_batch(wsf, project, 'zip',
                            workspace_id=workspace_id, uploader_id=g.current_user.id)
    img_dir = batch_img_dir(wsf, project, batch['job_name'])
    lbl_dir = batch_lbl_dir(wsf, project, batch['job_name'])
    img_dir.mkdir(parents=True, exist_ok=True)
    lbl_dir.mkdir(parents=True, exist_ok=True)
    imgs_done = lbls_done = 0
    cls_names = []
    from app.core.paths import project_dir as _pd_fn
    from app.core import db_index as _dbi
    _pd = _pd_fn(wsf, project)
    try:
        with zipfile.ZipFile(file) as zf:
            names = zf.namelist()
            for n in names:
                if Path(n).name in ('data.yaml', 'data.yml'):
                    with zf.open(n) as f:
                        try:
                            cls_names = yaml.safe_load(f.read()).get('names', [])
                        except Exception:
                            pass
            img_paths = []
            for n in names:
                p   = Path(n)
                ext = p.suffix.lower()
                if ext in ALLOWED_IMG:
                    dest = img_dir / p.name
                    with zf.open(n) as src, open(dest, 'wb') as dst:
                        dst.write(src.read())
                    imgs_done += 1
                    img_paths.append(dest)
                elif ext == '.txt' and p.name != 'classes.txt':
                    dest = lbl_dir / p.name
                    with zf.open(n) as src:
                        data = src.read()
                    dest.write_bytes(data)
                    if data.strip():
                        lbls_done += 1

        # Merge classes and get remap dict: source_idx → project_id
        remap = _merge_classes_and_remap(wsf, project, cls_names) if cls_names else {}

        # Remap all written label files if indices differ
        if remap:
            for lbl_path in lbl_dir.iterdir():
                if lbl_path.suffix == '.txt':
                    _remap_label_file(lbl_path, remap)

        # Register images in SQLite index + main images table
        try:
            from app import db
            from app.models.image import Image as ImageModel
            for dest in img_paths:
                idx_res = _dbi.add_image(_pd, dest, batch['job_name'], keep_duplicate=True)
                if not idx_res.get('duplicate'):
                    lbl_f = lbl_dir / (dest.stem + '.txt')
                    has_ann = lbl_f.exists() and bool(lbl_f.read_text(errors='ignore').strip())
                    db.session.add(ImageModel(
                        workspace_id=workspace_id,
                        project=project,
                        batch_id=batch.get('batch_db_id'),
                        filename=dest.name,
                        rel_path=idx_res['path'],
                        uploaded_by=g.current_user.id,
                        is_annotated=has_ann,
                    ))
            db.session.commit()
        except Exception:
            pass

        batches = load_uploads(wsf, project)
        for b in batches:
            if b['upload_id'] == batch['upload_id']:
                b['cls_names'] = cls_names
                b['source']    = 'zip'
        save_uploads(wsf, project, batches)

        return jsonify({
            'success': True, 'upload_id': batch['upload_id'],
            'images_imported': imgs_done, 'labels_imported': lbls_done,
            'cls_names': cls_names, 'classes_merged': len(cls_names),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@uploads_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/extract_frames',
                   methods=['POST'])
@login_required
@workspace_role_required('owner', 'editor')
def api_extract_frames(workspace_id, project):
    """
    Extract frames from video using ffmpeg (preferred) or OpenCV (fallback).
    Supports ALL formats ffmpeg can decode:
      mp4, avi, mov, mkv, wmv, flv, ts, m2ts, mts, m4v, webm,
      .dav (Dahua CCTV), .h264, .h265, .264, .265, and more.
    """
    import subprocess, tempfile

    wsf  = _wsf(workspace_id)
    file = request.files.get('file')
    try:
        fps = int(request.form.get('fps', 5))
    except (TypeError, ValueError):
        return jsonify({'error': 'fps must be an integer between 1 and 30'}), 400
    if not 1 <= fps <= 30:
        return jsonify({'error': 'fps must be between 1 and 30'}), 400
    output_format = request.form.get('format', 'jpg')
    if output_format not in ('jpg', 'png'):
        return jsonify({'error': 'format must be jpg or png'}), 400
    size = request.form.get('size', 'original')
    dimensions = {'original': None, '1080p': (1920,1080), '720p': (1280,720), '480p': (854,480)}
    if size == 'custom':
        try:
            width, height = int(request.form.get('custom_w', 0)), int(request.form.get('custom_h', 0))
        except (TypeError, ValueError):
            return jsonify({'error': 'Custom dimensions must be integers'}), 400
        if not (64 <= width <= 7680 and 64 <= height <= 4320):
            return jsonify({'error': 'Custom dimensions are out of range'}), 400
        output_size = (width, height)
    elif size in dimensions:
        output_size = dimensions[size]
    else:
        return jsonify({'error': 'Invalid output size'}), 400

    if not file:
        return jsonify({'error': 'No file'}), 400

    # Try ffmpeg first — faster and supports all formats including .dav CCTV
    ffmpeg_ok = False
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True, timeout=5)
        ffmpeg_ok = True
    except Exception:
        pass

    get_or_create_project(wsf, project)
    batch   = _create_batch(wsf, project, 'video',
                            workspace_id=workspace_id, uploader_id=g.current_user.id)
    img_dir = batch_img_dir(wsf, project, batch['job_name'])
    lbl_dir = batch_lbl_dir(wsf, project, batch['job_name'])
    img_dir.mkdir(parents=True, exist_ok=True)
    lbl_dir.mkdir(parents=True, exist_ok=True)

    suffix   = Path(file.filename).suffix.lower() or '.tmp'
    # Build unique stem: video_name + job timestamp
    # This guarantees no filename collision even if same video extracted twice
    import re as _re
    raw_stem  = Path(file.filename).stem
    safe_stem = _re.sub(r'[^\w]', '_', raw_stem)[:40]
    # Extract compact timestamp from job_name: job_2026-01-15_10-30-45_123
    # → "202601151030"  (12 chars, always unique per job)
    ts_part   = batch['job_name'].replace('job_', '').replace('-','').replace('_','')[:12]
    stem      = f'{safe_stem}_{ts_part}'  # e.g. cctv_cam1_202601151030

    # Save uploaded video to temp file
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        file.save(str(tmp_path))
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        return jsonify({'error': f'Failed to save video: {e}'}), 500

    saved = 0
    try:
        if ffmpeg_ok:
            # ffmpeg: extracts exactly fps frames per second
            # supports .dav, H.264, H.265, HEVC, all RTSP/DVR formats
            out_pat = str(img_dir / f'{stem}_frame%06d.{output_format}')
            filters = f'fps={fps}'
            if output_size:
                filters += f',scale={output_size[0]}:{output_size[1]}'
            cmd = [
                'ffmpeg', '-y',
                '-i', str(tmp_path),
                '-vf', filters,
                '-vsync', 'vfr',
                '-q:v', '2',        # JPEG quality (1=best, 31=worst)
                '-threads', '0',    # use all CPU cores
                out_pat
            ]
            proc = subprocess.run(cmd, capture_output=True, timeout=600)
            saved = sum(1 for f in img_dir.iterdir()
                        if f.suffix.lower() == '.' + output_format
                        and f.stem.startswith(stem + '_frame'))
            if saved == 0 and proc.returncode != 0:
                err = proc.stderr.decode(errors='ignore')
                # Try without -vsync (some older ffmpeg versions)
                cmd2 = [c for c in cmd if c != 'vfr' and c != '-vsync']
                proc2 = subprocess.run(cmd2, capture_output=True, timeout=600)
                saved = sum(1 for f in img_dir.iterdir()
                            if f.suffix.lower() == '.' + output_format
                            and f.stem.startswith(stem + '_frame'))
                if saved == 0:
                    return jsonify({'error': f'ffmpeg could not decode this video: {err[-200:]}'}), 400
        else:
            # Fallback: OpenCV
            try:
                import cv2
            except ImportError:
                return jsonify({'error':
                    'Install ffmpeg for video support: https://ffmpeg.org/download.html'
                }), 400
            cap     = cv2.VideoCapture(str(tmp_path))
            vid_fps = cap.get(cv2.CAP_PROP_FPS) or 30
            interval = max(1, int(vid_fps / fps))
            frame_n  = 0
            while True:
                ok, frame = cap.read()
                if not ok: break
                if frame_n % interval == 0:
                    if output_size:
                        frame = cv2.resize(frame, output_size)
                    if cv2.imwrite(str(img_dir / f'{stem}_frame{frame_n:06d}.{output_format}'), frame):
                        saved += 1
                frame_n += 1
            cap.release()

        # ── Register every extracted frame in both DB mirrors ────────────
        # This step did not exist before: extracted frames were written to
        # disk and registered NOWHERE, so a whole video's worth of frames
        # showed up as files with no DB row in either mirror (the exact
        # drift the consistency checker now reports for ws7/mahes).
        frame_paths = sorted(
            f for f in img_dir.iterdir()
            if f.suffix.lower() == '.' + output_format and f.stem.startswith(stem + '_frame')
        )
        _register_images(wsf, project, workspace_id, g.current_user.id,
                         batch, frame_paths)

        return jsonify({
            'success':          True,
            'frames_extracted': saved,
            'upload_id':        batch['upload_id'],
            'job_name':         batch['job_name'],
        })

    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Video extraction timed out (>10 min)'}), 408
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        tmp_path.unlink(missing_ok=True)


@uploads_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/uploads/<int:uid>/assign',
                   methods=['POST', 'DELETE'])
@login_required
@workspace_role_required('owner', 'editor')
def api_assign_batch(workspace_id, project, uid):
    wsf     = _wsf(workspace_id)
    batches = load_uploads(wsf, project)
    batch   = next((b for b in batches if b['upload_id'] == uid), None)
    if not batch:
        return jsonify({'error': 'Batch not found'}), 404

    batch_db_id = batch.get('batch_db_id')

    if request.method == 'DELETE':
        try:
            from app import db
            from app.models.assignment import Assignment
            if batch_db_id:
                Assignment.query.filter_by(batch_id=batch_db_id).delete()
                db.session.commit()
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        return jsonify({'success': True})

    # POST — create / replace assignment
    data    = request.json or {}
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({'error': 'user_id required'}), 400

    try:
        from app import db
        from app.models.assignment import Assignment
        from app.models.workspace import WorkspaceMember

        member = WorkspaceMember.query.filter_by(
            workspace_id=workspace_id, user_id=user_id).first()
        if not member:
            return jsonify({'error': 'User is not a workspace member'}), 400

        if not batch_db_id:
            return jsonify({'error': 'Batch not linked to DB — cannot assign'}), 400

        counts = _count_batch(wsf, project, batch['job_name'])

        Assignment.query.filter_by(batch_id=batch_db_id).delete()
        a = Assignment(
            workspace_id = workspace_id,
            project      = project,
            batch_id     = batch_db_id,
            assigned_to  = int(user_id),
            assigned_by  = g.current_user.id,
            note         = data.get('note', ''),
            total_images = counts['total'],
        )
        db.session.add(a)
        db.session.commit()
        return jsonify({'success': True, 'assignment': a.to_dict()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

