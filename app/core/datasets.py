"""
Dataset operations — files NEVER move.

When a batch is added to the dataset:
  - images.status is set to 'in_dataset'
  - images.split  is set to 'train' | 'val' | 'test'
  - The image and label files stay in Active_Work/ forever
  - DB is the only source of truth for what is "in the dataset"

Legacy datasets (created before this version) whose files are already in
Completed_Datasets/ continue to work — list_datasets() returns both.
"""
import json
import random
from datetime import datetime
from pathlib import Path

from app.core.paths import (completed_datasets_dir, batch_img_dir, batch_lbl_dir,
                             project_dir)
from app.core.media import ALLOWED_IMG
from app.core.yolo import is_valid_annotation_file
from app.core.storage import load_project_meta, load_uploads, save_uploads


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_workspace_id(ws_folder: str):
    """Resolve integer workspace_id from folder name (needed for DB queries)."""
    try:
        from app.models.workspace import Workspace
        ws = Workspace.query.filter_by(folder_name=ws_folder).first()
        return ws.id if ws else None
    except Exception:
        return None


def _collect_for_dataset(img_dir: Path, lbl_dir: Path):
    """
    Yield (img_path, lbl_path, is_null) for images ready to add to the dataset:
      - Annotated : .txt has valid YOLO content  → is_null=False
      - Null/bg   : .txt exists but is empty     → is_null=True
    Images with no .txt file are NOT yielded — they stay pending.
    """
    if not img_dir.exists():
        return
    for img in sorted(img_dir.iterdir()):
        if img.suffix.lower() not in ALLOWED_IMG:
            continue
        lbl = lbl_dir / (img.stem + '.txt')
        if not lbl.exists():
            continue
        content = lbl.read_text(encoding='utf-8', errors='ignore').strip()
        is_null = (content == '' or content == '__null__')
        if is_null or is_valid_annotation_file(lbl):
            yield img, lbl, is_null


# ── Add batch to dataset (no file moves) ─────────────────────────────────────

def add_batch_to_dataset(ws_folder: str, project: str, uid: int,
                         train_r: float = 0.70,
                         val_r:   float = 0.15,
                         test_r:  float = 0.15,
                         workspace_id: int = None,
                         reviewer_id:  int = None) -> dict:
    batches = load_uploads(ws_folder, project)
    batch   = next((b for b in batches if b['upload_id'] == uid), None)
    if not batch:
        return None

    img_dir = batch_img_dir(ws_folder, project, batch['job_name'])
    lbl_dir = batch_lbl_dir(ws_folder, project, batch['job_name'])
    pd      = project_dir(ws_folder, project)

    if not img_dir.exists():
        return {'success': False,
                'error': 'Batch folder not found. Was it deleted?'}

    dataset_pairs = list(_collect_for_dataset(img_dir, lbl_dir))
    total         = len(dataset_pairs)

    # Images with no label file at all = not yet annotated
    unannotated_count = sum(
        1 for img in img_dir.iterdir()
        if img.suffix.lower() in ALLOWED_IMG
        and not (lbl_dir / (img.stem + '.txt')).exists()
    )

    if total == 0:
        return {
            'success':         False,
            'error':           (f'No annotated images in this batch '
                                f'({unannotated_count} unannotated). '
                                'Annotate at least one image first.'),
            'moved_annotated': 0,
            'remaining_raw':   unannotated_count,
            'split_counts':    {'train': 0, 'val': 0, 'test': 0},
        }

    # ── Compute split sizes ───────────────────────────────────────────────────
    random.shuffle(dataset_pairs)
    s = train_r + val_r + test_r
    if s > 0:
        train_r /= s
        val_r   /= s

    n_train = round(total * train_r)
    n_val   = round(total * val_r)
    n_test  = total - n_train - n_val

    if total == 1:
        n_train, n_val, n_test = 1, 0, 0
    elif total == 2:
        n_train, n_val, n_test = 1, 0, 1
    elif total >= 3:
        n_train = max(1, n_train)
        n_val   = max(1, n_val)
        n_test  = total - n_train - n_val

    buckets = [
        ('train', dataset_pairs[:n_train]),
        ('valid', dataset_pairs[n_train:n_train + n_val]),
        ('test',  dataset_pairs[n_train + n_val:]),
    ]
    split_counts = {'train': n_train, 'val': n_val, 'test': n_test}

    # ── Update DB — files stay exactly where they are ─────────────────────────
    ws_id = workspace_id or _get_workspace_id(ws_folder)
    if ws_id:
        try:
            from app import db
            from app.models.image import Image as ImageModel
            now = datetime.utcnow()
            for split_name, pairs in buckets:
                for img, lbl, is_null in pairs:
                    rel_path = str(img.relative_to(pd))
                    img_row  = ImageModel.query.filter_by(
                        workspace_id=ws_id, project=project, rel_path=rel_path,
                    ).first()
                    if img_row:
                        img_row.status             = 'in_dataset'
                        img_row.split              = split_name
                        img_row.reviewed_by        = reviewer_id
                        img_row.reviewed_at        = now
                        img_row.added_to_dataset_at = now
                        img_row.is_null            = is_null
                        img_row.is_annotated       = True
            db.session.commit()
        except Exception:
            pass

    # ── Update _uploads.json ──────────────────────────────────────────────────
    batch_fully_done = (unannotated_count == 0)
    for b in batches:
        if b['upload_id'] == uid:
            b['in_dataset']     = batch_fully_done
            b['partial_dataset'] = not batch_fully_done
    save_uploads(ws_folder, project, batches)

    return {
        'success':         True,
        'moved_annotated': total,      # key name kept for frontend compat
        'remaining_raw':   unannotated_count,
        'split_counts':    split_counts,
    }


# ── List datasets ─────────────────────────────────────────────────────────────

def list_datasets(ws_folder: str, project: str) -> list:
    """
    Return all datasets for a project.

    Two sources — combined and sorted newest-first:
      1. DB-based  : upload batches that have images with status='in_dataset'
                     (files are still in Active_Work)
      2. Legacy    : folders in Completed_Datasets/ (files were moved before
                     this upgrade — backward-compatible read-only view)
    """
    result  = []
    seen    = set()   # batch_ids already covered by DB to avoid duplicates

    # ── 1. DB-based datasets ──────────────────────────────────────────────────
    ws_id = _get_workspace_id(ws_folder)
    if ws_id:
        try:
            from app import db
            from app.models.upload_batch import UploadBatch
            from app.models.image import Image as ImageModel

            # All batches that have at least one in_dataset image
            batch_ids = (
                db.session.query(ImageModel.batch_id)
                .filter(
                    ImageModel.workspace_id == ws_id,
                    ImageModel.project      == project,
                    ImageModel.status       == 'in_dataset',
                    ImageModel.batch_id.isnot(None),
                )
                .distinct()
                .all()
            )

            for (bid,) in batch_ids:
                seen.add(bid)
                imgs = ImageModel.query.filter_by(
                    workspace_id=ws_id, project=project,
                    batch_id=bid, status='in_dataset',
                ).all()

                split_counts = {'train': 0, 'val': 0, 'test': 0}
                null_count   = 0
                added_at     = None
                for img in imgs:
                    if img.split in split_counts:
                        split_counts[img.split] += 1
                    if img.is_null:
                        null_count += 1
                    if img.added_to_dataset_at:
                        if added_at is None or img.added_to_dataset_at > added_at:
                            added_at = img.added_to_dataset_at

                batch = db.session.get(UploadBatch, bid)
                result.append({
                    'dataset_id':   f'db_{bid}',
                    'batch_id':     bid,
                    'batch_name':   batch.batch_name if batch else '',
                    'datetime_str': (added_at.strftime('%Y-%m-%d %H:%M')
                                     if added_at else ''),
                    'created_at':   added_at.isoformat() if added_at else '',
                    'total_images': len(imgs),
                    'null_count':   null_count,
                    'split_counts': split_counts,
                    'source':       'db',
                })
        except Exception:
            pass

    # ── 2. Legacy Completed_Datasets/ folders ─────────────────────────────────
    cd = completed_datasets_dir(ws_folder, project)
    if cd.exists():
        for ds_dir in sorted(cd.iterdir(), reverse=True):
            if not ds_dir.is_dir():
                continue
            mf = ds_dir / 'dataset.json'
            try:
                ds = (json.loads(mf.read_text(encoding='utf-8'))
                      if mf.exists()
                      else {'dataset_id': ds_dir.name,
                            'datetime_str': ds_dir.name})
            except Exception:
                ds = {'dataset_id': ds_dir.name, 'datetime_str': ds_dir.name}

            split_counts = {}
            total_images = 0
            for folder, key in [('train','train'), ('valid','val'), ('test','test')]:
                sid = ds_dir / folder / 'images'
                n   = (sum(1 for f in sid.iterdir()
                           if f.suffix.lower() in ALLOWED_IMG)
                       if sid.exists() else 0)
                split_counts[key] = n
                total_images     += n

            if total_images == 0:
                continue   # skip empty folders

            ds['split_counts'] = split_counts
            ds['total_images'] = total_images
            ds['source']       = 'legacy'
            result.append(ds)

    return result
