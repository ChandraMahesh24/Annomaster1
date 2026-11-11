"""
Dataset API.

Two dataset types are handled transparently:
  db_<batch_id>   — new style: files stay in Active_Work, status tracked in DB
  <folder_name>   — legacy:    files physically moved to Completed_Datasets/
                                (created before the files-never-move upgrade)
"""
import io
import json
import math
import shutil
import yaml
import zipfile
from datetime import datetime
from pathlib import Path
from flask import Blueprint, request, jsonify, send_file, g
from app import db
from app.utils.security import login_required, workspace_role_required
from app.core.datasets import list_datasets
from app.core.paths import (completed_datasets_dir, project_dir,
                              active_work_dir, batch_img_dir, batch_lbl_dir)
from app.core.media import ALLOWED_IMG
from app.core.yolo import is_valid_annotation_file
from app.core.storage import (load_project_meta, load_uploads,
                               save_uploads, next_upload_id)
from app.models.workspace import Workspace

datasets_bp = Blueprint('datasets', __name__)


def _wsf(wid): return Workspace.query.get_or_404(int(wid)).folder_name


def _is_db_dataset(dataset_id: str) -> bool:
    return dataset_id.startswith('db_')


def _batch_id_from(dataset_id: str) -> int:
    return int(dataset_id[3:])   # strip 'db_' prefix


# ── List datasets ─────────────────────────────────────────────────────────────

@datasets_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/datasets')
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def api_datasets(workspace_id, project):
    from app.core import tags as tags_mod
    wsf      = _wsf(workspace_id)
    tag_map  = tags_mod.dataset_tags_map(wsf, project)
    # Datasets are derived (from DB rows or folders), so their tags are looked
    # up by dataset_id and merged in here rather than stored on the record.
    return jsonify([{**d, 'tags': tag_map.get(d.get('dataset_id'), [])}
                    for d in list_datasets(wsf, project)])


@datasets_bp.route(
    '/api/workspaces/<int:workspace_id>/projects/<project>/datasets/<dataset_id>/tags',
    methods=['PUT'])
@login_required
@workspace_role_required('owner', 'editor')
def api_set_dataset_tags(workspace_id, project, dataset_id):
    from app.core import tags as tags_mod
    cleaned = tags_mod.set_dataset_tags(_wsf(workspace_id), project, dataset_id,
                                        (request.json or {}).get('tags'))
    return jsonify({'success': True, 'tags': cleaned})


# ── Dataset images (paginated) ────────────────────────────────────────────────

@datasets_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/datasets/images')
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def api_datasets_images(workspace_id, project):
    wsf      = _wsf(workspace_id)
    page     = max(1, int(request.args.get('page', 1)))
    per_page = max(10, min(200, int(request.args.get('per_page', 40))))
    split_f  = request.args.get('split', 'all')
    if split_f == 'valid': split_f = 'val'   # normalize legacy filter value
    anno_f   = request.args.get('annotated', 'all')
    q        = request.args.get('q', '').lower()
    class_f  = request.args.get('class_id', '')
    dataset_f = request.args.get('dataset_id', 'all')

    pd       = project_dir(wsf, project)
    all_items = []

    # ── DB-based images (files in Active_Work) ────────────────────────────────
    try:
        from app.models.image import Image as ImageModel
        query = ImageModel.query.filter_by(
            workspace_id=workspace_id,
            project=project,
            status='in_dataset',
        )
        if dataset_f != 'all' and _is_db_dataset(dataset_f):
            query = query.filter_by(batch_id=_batch_id_from(dataset_f))
        elif dataset_f != 'all' and not _is_db_dataset(dataset_f):
            query = query.filter(False)   # non-db filter → no DB results

        for img_row in query.all():
            img_path = pd / img_row.rel_path
            lbl_path = img_path.parent.parent / 'labels' / (img_path.stem + '.txt')

            has_anno  = is_valid_annotation_file(lbl_path)
            is_null   = img_row.is_null
            class_ids = []
            if has_anno and lbl_path.exists():
                for line in lbl_path.read_text(errors='ignore').splitlines():
                    parts = line.strip().split()
                    if parts:
                        try: class_ids.append(int(parts[0]))
                        except ValueError: pass

            all_items.append({
                'path':       img_row.rel_path,
                'name':       img_row.filename,
                'split':      img_row.split or 'train',
                'dataset_id': f'db_{img_row.batch_id}' if img_row.batch_id else 'db',
                'annotated':  has_anno,
                'is_null':    is_null,
                'class_ids':  class_ids,
                'source':     'db',
            })
    except Exception:
        pass

    # ── Legacy images (files in Completed_Datasets/) ──────────────────────────
    cd = completed_datasets_dir(wsf, project)
    if cd.exists() and (dataset_f == 'all' or not _is_db_dataset(dataset_f)):
        for ds_dir in sorted(cd.iterdir(), reverse=True):
            if not ds_dir.is_dir():
                continue
            ds_id = ds_dir.name
            if dataset_f != 'all' and ds_id != dataset_f:
                continue
            for split in ('train', 'valid', 'test'):
                img_dir = ds_dir / split / 'images'
                lbl_dir = ds_dir / split / 'labels'
                if not img_dir.exists():
                    continue
                for img in sorted(img_dir.iterdir()):
                    if img.suffix.lower() not in ALLOWED_IMG:
                        continue
                    rel      = str(img.relative_to(pd))
                    lbl      = lbl_dir / (img.stem + '.txt')
                    has_anno = is_valid_annotation_file(lbl)
                    _lbl_c   = (lbl.read_text(encoding='utf-8', errors='ignore').strip()
                                if lbl.exists() else None)
                    is_null  = _lbl_c is not None and (_lbl_c == '' or _lbl_c == '__null__')
                    class_ids = []
                    if has_anno:
                        for line in lbl.read_text(errors='ignore').splitlines():
                            parts = line.strip().split()
                            if parts:
                                try: class_ids.append(int(parts[0]))
                                except ValueError: pass
                    all_items.append({
                        'path':       rel,
                        'name':       img.name,
                        'split':      split,
                        'dataset_id': ds_id,
                        'annotated':  has_anno,
                        'is_null':    is_null,
                        'class_ids':  class_ids,
                        'source':     'legacy',
                    })

    # ── Filters ───────────────────────────────────────────────────────────────
    if q:
        all_items = [i for i in all_items if q in i['name'].lower()]
    if split_f != 'all':
        all_items = [i for i in all_items if i['split'] == split_f]
    if anno_f == 'yes':
        all_items = [i for i in all_items if i['annotated']]
    elif anno_f == 'no':
        all_items = [i for i in all_items if not i['annotated'] and not i['is_null']]
    elif anno_f == 'null':
        all_items = [i for i in all_items if i['is_null']]
    if class_f:
        try:
            cid = int(class_f)
            all_items = [i for i in all_items if cid in i['class_ids']]
        except ValueError:
            pass

    total       = len(all_items)
    total_pages = max(1, math.ceil(total / per_page))
    page        = min(page, total_pages)
    start       = (page - 1) * per_page
    return jsonify({
        'items': all_items[start:start + per_page],
        'pagination': {
            'page': page, 'per_page': per_page,
            'total': total, 'total_pages': total_pages,
        },
    })


# ── Delete individual images from dataset ─────────────────────────────────────

@datasets_bp.route(
    '/api/workspaces/<int:workspace_id>/projects/<project>/datasets/images/delete',
    methods=['POST'])
@login_required
@workspace_role_required('owner', 'editor')
def api_delete_dataset_images(workspace_id, project):
    wsf     = _wsf(workspace_id)
    data    = request.json or {}
    paths   = data.get('paths', [])
    pd      = project_dir(wsf, project)
    deleted = 0

    for rel in paths:
        # Try DB first
        try:
            from app.models.image import Image as ImageModel
            img_row = ImageModel.query.filter_by(
                workspace_id=workspace_id, project=project, rel_path=rel,
            ).first()
            if img_row:
                img_row.status             = 'active'
                img_row.split              = None
                img_row.added_to_dataset_at = None
                img_row.reviewed_by        = None
                img_row.reviewed_at        = None
                db.session.commit()
                deleted += 1
                continue
        except Exception:
            pass

        # Legacy — physically delete from Completed_Datasets
        img_path = pd / rel
        if img_path.exists() and img_path.is_file():
            lbl_path = img_path.parent.parent / 'labels' / (img_path.stem + '.txt')
            img_path.unlink(missing_ok=True)
            lbl_path.unlink(missing_ok=True)
            deleted += 1

    return jsonify({'success': True, 'deleted': deleted})


# ── Delete entire dataset ─────────────────────────────────────────────────────

@datasets_bp.route(
    '/api/workspaces/<int:workspace_id>/projects/<project>/datasets/<path:dataset_id>',
    methods=['DELETE'])
@login_required
@workspace_role_required('owner', 'editor')
def api_delete_dataset(workspace_id, project, dataset_id):
    wsf = _wsf(workspace_id)

    if _is_db_dataset(dataset_id):
        # DB dataset — set all images back to active
        try:
            from app.models.image import Image as ImageModel
            bid = _batch_id_from(dataset_id)
            ImageModel.query.filter_by(
                workspace_id=workspace_id, project=project,
                batch_id=bid, status='in_dataset',
            ).update({
                'status':             'active',
                'split':              None,
                'added_to_dataset_at': None,
                'reviewed_by':        None,
                'reviewed_at':        None,
            }, synchronize_session=False)
            db.session.commit()
        except Exception:
            pass
    else:
        # Legacy — remove the Completed_Datasets folder
        ds_dir = completed_datasets_dir(wsf, project) / dataset_id
        if ds_dir.exists():
            shutil.rmtree(ds_dir)

    return jsonify({'success': True})


# ── Dataset media (for annotation viewer in read-only mode) ───────────────────

@datasets_bp.route(
    '/api/workspaces/<int:workspace_id>/projects/<project>/datasets/<path:dataset_id>/media')
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def api_dataset_media(workspace_id, project, dataset_id):
    wsf = _wsf(workspace_id)
    pd  = project_dir(wsf, project)

    if _is_db_dataset(dataset_id):
        # Serve from Active_Work via DB
        try:
            from app.models.image import Image as ImageModel
            bid  = _batch_id_from(dataset_id)
            rows = ImageModel.query.filter_by(
                workspace_id=workspace_id, project=project,
                batch_id=bid, status='in_dataset',
            ).all()
            media, ann = [], []
            for row in rows:
                img_path = pd / row.rel_path
                lbl_path = img_path.parent.parent / 'labels' / (img_path.stem + '.txt')
                media.append({
                    'path':  row.rel_path,
                    'name':  row.filename,
                    'split': row.split or 'train',
                    'job':   dataset_id,
                })
                if lbl_path.exists() and is_valid_annotation_file(lbl_path):
                    ann.append(row.rel_path)
            meta = load_project_meta(wsf, project)
            return jsonify({'media': media, 'annotated': ann, 'null_paths': [],
                            'classes': meta.get('classes', []),
                            'dataset_id': dataset_id, 'readonly': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    else:
        # Legacy — scan Completed_Datasets folder
        ds_dir = completed_datasets_dir(wsf, project) / dataset_id
        if not ds_dir.exists():
            return jsonify({'error': 'Dataset not found'}), 404
        media, ann = [], []
        for split in ('train', 'valid', 'test', ''):
            src_img = (ds_dir / split / 'images') if split else (ds_dir / 'images')
            src_lbl = (ds_dir / split / 'labels') if split else (ds_dir / 'labels')
            if not src_img.exists():
                continue
            for img in sorted(src_img.iterdir()):
                if img.suffix.lower() not in ALLOWED_IMG:
                    continue
                rel = str(img.relative_to(pd))
                lbl = src_lbl / (img.stem + '.txt') if src_lbl.exists() else None
                media.append({'path': rel, 'name': img.name,
                              'split': split or 'none', 'job': dataset_id})
                if lbl and lbl.exists() and is_valid_annotation_file(lbl):
                    ann.append(rel)
        meta = load_project_meta(wsf, project)
        return jsonify({'media': media, 'annotated': ann, 'null_paths': [],
                        'classes': meta.get('classes', []),
                        'dataset_id': dataset_id, 'readonly': True})


# ── Move dataset back to Active Work ─────────────────────────────────────────

@datasets_bp.route(
    '/api/workspaces/<int:workspace_id>/projects/<project>/datasets/<path:dataset_id>/move_to_active',
    methods=['POST'])
@login_required
@workspace_role_required('owner', 'editor')
def api_dataset_move_to_active(workspace_id, project, dataset_id):
    wsf = _wsf(workspace_id)

    if _is_db_dataset(dataset_id):
        # DB dataset — files never moved, just reset status in DB
        try:
            from app.models.image import Image as ImageModel
            bid     = _batch_id_from(dataset_id)
            updated = ImageModel.query.filter_by(
                workspace_id=workspace_id, project=project,
                batch_id=bid, status='in_dataset',
            ).update({
                'status':             'active',
                'split':              None,
                'added_to_dataset_at': None,
                'reviewed_by':        None,
                'reviewed_at':        None,
            }, synchronize_session=False)
            db.session.commit()

            # Update _uploads.json
            wsf_folder = _wsf(workspace_id)
            batches = load_uploads(wsf_folder, project)
            from app.models.upload_batch import UploadBatch
            ub = UploadBatch.query.get(bid)
            if ub:
                for b in batches:
                    if b.get('batch_db_id') == bid:
                        b['in_dataset'] = False
                        b.pop('partial_dataset', None)
                save_uploads(wsf_folder, project, batches)

            return jsonify({'success': True, 'moved': updated})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    else:
        # Legacy — physically move files from Completed_Datasets back to Active_Work
        ds_dir = completed_datasets_dir(wsf, project) / dataset_id
        if not ds_dir.exists():
            return jsonify({'error': 'Dataset not found'}), 404

        now      = datetime.now()
        job_name = now.strftime('job_%Y-%m-%d_%H-%M-%S_') + f'{now.microsecond // 1000:03d}'
        aw_img   = batch_img_dir(wsf, project, job_name)
        aw_lbl   = batch_lbl_dir(wsf, project, job_name)
        aw_img.mkdir(parents=True, exist_ok=True)
        aw_lbl.mkdir(parents=True, exist_ok=True)

        moved_imgs = 0
        for split in ('train', 'valid', 'test', ''):
            src_img = (ds_dir / split / 'images') if split else (ds_dir / 'images')
            src_lbl = (ds_dir / split / 'labels') if split else (ds_dir / 'labels')
            if not src_img.exists():
                continue
            for img in src_img.iterdir():
                if img.suffix.lower() not in ALLOWED_IMG:
                    continue
                dst_img = aw_img / img.name
                counter = 1
                while dst_img.exists():
                    dst_img = aw_img / f"{img.stem}_{counter}{img.suffix}"
                    counter += 1
                shutil.move(str(img), str(dst_img))
                lbl = (src_lbl / (img.stem + '.txt')) if src_lbl.exists() else None
                if lbl and lbl.exists():
                    shutil.move(str(lbl), str(aw_lbl / (dst_img.stem + '.txt')))
                moved_imgs += 1

        uid     = next_upload_id(wsf, project)
        batches = load_uploads(wsf, project)
        batches.append({
            'upload_id': uid, 'job_name': job_name,
            'datetime_str': job_name, 'source': 'images',
            'label': f'Moved from dataset {dataset_id}',
        })
        save_uploads(wsf, project, batches)
        shutil.rmtree(ds_dir, ignore_errors=True)
        return jsonify({'success': True, 'job_name': job_name,
                        'upload_id': uid, 'moved': moved_imgs})


# ── Export all dataset images as YOLO ZIP ────────────────────────────────────

@datasets_bp.route('/api/workspaces/<int:workspace_id>/projects/<project>/export',
                    methods=['POST'])
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def api_export(workspace_id, project):
    wsf     = _wsf(workspace_id)
    meta    = load_project_meta(wsf, project)
    classes = meta.get('classes', [])
    pd      = project_dir(wsf, project)
    buf     = io.BytesIO()

    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('data.yaml', yaml.dump(
            {'names': [c['name'] for c in classes], 'nc': len(classes)}))

        # DB-based images (files in Active_Work)
        try:
            from app.models.image import Image as ImageModel
            rows = ImageModel.query.filter_by(
                workspace_id=workspace_id, project=project, status='in_dataset',
            ).all()
            for row in rows:
                img_path = pd / row.rel_path
                lbl_path = img_path.parent.parent / 'labels' / (img_path.stem + '.txt')
                split    = row.split or 'train'
                if img_path.exists():
                    zf.write(img_path, f'{split}/images/{img_path.name}')
                if lbl_path.exists():
                    content = lbl_path.read_text(errors='ignore').strip()
                    # Write empty .txt for null images (valid YOLO background)
                    arc_name = f'{split}/labels/{img_path.stem}.txt'
                    if content == '' or content == '__null__':
                        zf.writestr(arc_name, '')
                    elif is_valid_annotation_file(lbl_path):
                        zf.write(lbl_path, arc_name)
        except Exception:
            pass

        # Legacy Completed_Datasets images
        cd = completed_datasets_dir(wsf, project)
        if cd.exists():
            for ds_dir in cd.iterdir():
                if not ds_dir.is_dir():
                    continue
                for split in ('train', 'valid', 'test'):
                    for sub, arc in [('images', f'{split}/images'),
                                     ('labels', f'{split}/labels')]:
                        subdir = ds_dir / split / sub
                        if subdir.exists():
                            for f in subdir.iterdir():
                                zf.write(f, f'{arc}/{f.name}')

    buf.seek(0)
    return send_file(buf, mimetype='application/zip',
                     as_attachment=True,
                     download_name=f'{project}_dataset.zip')
