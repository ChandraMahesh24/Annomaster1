"""
Version snapshot builder.

Target folder structure (YOLO-standard, split-first):

  Versions/<version_name>/
    train/
      images/    ← training images
      labels/    ← YOLO .txt annotations
    val/
      images/
      labels/
    test/
      images/
      labels/
    data.yaml    ← nc, names, relative paths to splits
    README.md    ← stats + config summary

data.yaml paths:
    train: train/images
    val:   val/images
    test:  test/images

Why YOLO .txt over COCO JSON:
  - Direct training: no conversion needed for Ultralytics/Darknet/YOLOv8
  - O(1) per-image read: each image reads exactly one tiny .txt file
  - Atomic writes: one file = one image = no contention
  - Human-readable: open any file to inspect immediately
"""
import io
import json
import random
import shutil
import time
import zipfile
import yaml
import math
from datetime import datetime
from pathlib import Path

from app.core.paths import (versions_dir, completed_datasets_dir, project_dir)
from app.core.yolo import is_valid_annotation_file
from app.core.media import ALLOWED_IMG
from app.core.storage import (load_project_meta, load_versions, save_versions)


def stored_version_folder(ws_folder, project, version):
    """Untrusted/stale metadata must never make an empty path mean cwd."""
    raw = version.get('folder_path')
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        folder = Path(raw).resolve()
        root = versions_dir(ws_folder, project).resolve()
        if folder == root or not folder.is_relative_to(root) or not folder.is_dir():
            return None
        return folder
    except (OSError, ValueError, RuntimeError):
        return None


def _get_workspace_id(ws_folder: str):
    try:
        from app.models.workspace import Workspace
        ws = Workspace.query.filter_by(folder_name=ws_folder).first()
        return ws.id if ws else None
    except Exception:
        return None


def _build_version_folder(ws_folder, project, ver_id, ver_name,
                           ann_media, splits, classes, pp, augs) -> Path:
    """
    Build a version folder with split-first YOLO structure:
      <version>/train/images/  <version>/train/labels/
      <version>/val/images/    <version>/val/labels/
      <version>/test/images/   <version>/test/labels/
    """
    safe = ''.join(c if c.isalnum() or c in '-_.' else '_' for c in ver_name).strip(' .') or 'version'
    vdir = versions_dir(ws_folder, project) / safe
    if vdir.exists():
        vdir = versions_dir(ws_folder, project) / f"{safe}_{ver_id}"

    # Create split-first directory tree (matches your requested structure)
    for split in ('train', 'val', 'test'):
        (vdir / split / 'images').mkdir(parents=True, exist_ok=True)
        (vdir / split / 'labels').mkdir(parents=True, exist_ok=True)

    # Copy images + labels into correct split folders
    pd = project_dir(ws_folder, project)
    n_train = splits.get('train', 0)
    n_val   = splits.get('val', 0)

    buckets = [
        ('train', ann_media[:n_train]),
        ('val',   ann_media[n_train:n_train + n_val]),   # folder is 'val'
        ('test',  ann_media[n_train + n_val:]),
    ]

    def _unique_dst(folder: Path, filename: str) -> Path:
        """Return a unique path — adds _2, _3 suffix if name already exists."""
        dst = folder / filename
        if not dst.exists():
            return dst
        stem_u, ext_u = Path(filename).stem, Path(filename).suffix
        counter = 2
        while dst.exists():
            dst = folder / f'{stem_u}_{counter}{ext_u}'
            counter += 1
        return dst

    for split_name, items in buckets:
        img_out = vdir / split_name / 'images'
        lbl_out = vdir / split_name / 'labels'
        for item in items:
            img_path = Path(item['abs']) if item.get('abs') else pd / item['path']
            if not img_path.exists():
                continue
            dst_img = _unique_dst(img_out, img_path.name)
            shutil.copy2(str(img_path), str(dst_img))

            from app.core.paths import label_path_for_image
            lbl_path = label_path_for_image(img_path, create_dir=False)
            if lbl_path.exists():
                # Label must use same stem as the (possibly renamed) image
                dst_lbl = lbl_out / (dst_img.stem + '.txt')
                shutil.copy2(str(lbl_path), str(dst_lbl))

    # data.yaml — paths relative to version folder, split-first layout
    cls_names = [c['name'] for c in sorted(classes, key=lambda x: x['id'])]

    # Build sparse names list (handles deleted class IDs correctly)
    max_id = max((c['id'] for c in classes), default=-1)
    names_sparse = [''] * (max_id + 1)
    for c in classes:
        names_sparse[c['id']] = c['name']
    while names_sparse and not names_sparse[-1]:
        names_sparse.pop()

    yaml_data = {
        'path':  str(vdir),
        'train': 'train/images',   # ← split-first paths
        'val':   'val/images',
        'test':  'test/images',
        'nc':    len(classes),
        'names': names_sparse,
    }
    (vdir / 'data.yaml').write_text(
        yaml.dump(yaml_data, default_flow_style=False, allow_unicode=True),
        encoding='utf-8'
    )

    # README
    n_test = max(0, len(ann_media) - n_train - n_val)
    pp_lines  = []
    if pp.get('resize_mode', 'none') != 'none':
        pp_lines.append(f"- Resize: {pp['resize_mode']} → {pp.get('resize_w',1280)}×{pp.get('resize_h',720)}")
    if pp.get('auto_orient'): pp_lines.append('- Auto-orient: enabled')
    if pp.get('normalize'):   pp_lines.append('- Normalize: enabled')
    aug_lines = [f'- {a}' for a in augs] if augs else ['- None']

    readme = f"""# {ver_name}
Generated by AnnoMaster  ·  {datetime.now().strftime('%Y-%m-%d %H:%M')}

## Structure
```
{safe}/
  train/images/   train/labels/
  val/images/     val/labels/
  test/images/    test/labels/
  data.yaml
```

## Dataset Statistics
| Split | Images |
|-------|--------|
| Train | {n_train} |
| Val   | {n_val} |
| Test  | {n_test} |
| **Total** | **{n_train+n_val+n_test}** |

## Classes ({len(classes)})
{chr(10).join(f'  {c["id"]}: {c["name"]}' for c in sorted(classes, key=lambda x: x['id']))}

## Preprocessing
{chr(10).join(pp_lines) if pp_lines else '- None'}

## Augmentations
{chr(10).join(aug_lines)}
"""
    (vdir / 'README.md').write_text(readme, encoding='utf-8')
    return vdir


def create_version(ws_folder, project, data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError('Request body must be a JSON object')
    name = data.get('name')
    if name is not None and (not isinstance(name, str) or not name.strip() or len(name) > 100):
        raise ValueError('Version name must be between 1 and 100 characters')
    ratios = data.get('split_ratio', {})
    if not isinstance(ratios, dict):
        raise ValueError('split_ratio must be an object')
    try:
        train = float(ratios.get('train', .7))
        val = float(ratios.get('val', .2))
        test = float(ratios.get('test', max(0, 1 - train - val)))
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in (train, val, test)) or not math.isclose(train + val + test, 1, abs_tol=1e-6):
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError('Split ratios must be finite values between 0 and 1 totaling 1')
    if not isinstance(data.get('preprocessing', {}), dict) or not isinstance(data.get('augmentations', []), list):
        raise ValueError('Invalid preprocessing or augmentation settings')
    versions = load_versions(ws_folder, project)
    meta     = load_project_meta(ws_folder, project)
    classes  = meta.get('classes', [])
    split_r  = data.get('split_ratio', {})
    pp       = data.get('preprocessing', {})
    augs     = data.get('augmentations', [])
    cd       = completed_datasets_dir(ws_folder, project)
    pd       = project_dir(ws_folder, project)

    ann_media = []

    # ── 1. DB-based images (files stay in Active_Work) ────────────────────────
    ws_id = _get_workspace_id(ws_folder)
    if ws_id:
        try:
            from app.models.image import Image as ImageModel
            rows = ImageModel.query.filter_by(
                workspace_id=ws_id, project=project, status='in_dataset',
            ).all()
            for row in rows:
                img_path = pd / row.rel_path
                if not img_path.exists():
                    continue
                lbl_path = (img_path.parent.parent / 'labels'
                            / (img_path.stem + '.txt'))
                if row.is_null or is_valid_annotation_file(lbl_path):
                    ann_media.append({
                        'path': row.rel_path,
                        'name': row.filename,
                        'split': row.split or 'train',
                        'abs':  str(img_path),
                    })
        except Exception:
            pass

    # ── 2. Legacy Completed_Datasets/ images (backward compat) ───────────────
    if cd.exists():
        db_paths = {item['path'] for item in ann_media}
        for ds_dir in sorted(cd.iterdir(), reverse=True):
            if not ds_dir.is_dir():
                continue
            for split in ('train', 'valid', 'test'):
                img_dir = ds_dir / split / 'images'
                lbl_dir = ds_dir / split / 'labels'
                if not img_dir.exists():
                    continue
                for img in sorted(img_dir.iterdir()):
                    if img.suffix.lower() not in ALLOWED_IMG:
                        continue
                    rel = str(img.relative_to(pd))
                    if rel in db_paths:
                        continue   # already covered by DB
                    lbl = lbl_dir / (img.stem + '.txt')
                    if lbl.exists():
                        _c = lbl.read_text(errors='ignore').strip()
                        is_null = (_c == '' or _c == '__null__')
                        if is_null or is_valid_annotation_file(lbl):
                            ann_media.append({
                                'path': rel,
                                'name': img.name,
                                'split': split,
                                'abs':  str(img),
                            })

    if split_r.get('shuffle', True):
        random.shuffle(ann_media)

    train_r = float(split_r.get('train', 0.7))
    val_r   = float(split_r.get('val',   0.2))
    n_train = round(len(ann_media) * train_r)
    n_val   = min(len(ann_media) - n_train, round(len(ann_media) * val_r))
    n_test  = max(0, len(ann_media) - n_train - n_val)
    splits  = {'train': n_train, 'val': n_val, 'test': n_test}

    ver_name = data.get('name', f'v{len(versions)+1}')
    ver_id   = f"v{len(versions)+1}_{int(time.time())}"

    vdir = _build_version_folder(ws_folder, project, ver_id, ver_name,
                                 ann_media, splits, classes, pp, augs)
    folder_path = str(vdir)

    ver = {
        'id':               ver_id,
        'name':             ver_name,
        'note':             data.get('note', ''),
        'created_at':       datetime.now().strftime('%Y-%m-%d %H:%M'),
        'total_images':     len(ann_media),
        'annotated_images': len(ann_media),
        'num_classes':      len(classes),
        'splits':           splits,
        'preprocessing':    pp,
        'augmentations':    augs,
        'split_ratio':      split_r,
        'folder_path':      folder_path,
        'folder_name':      Path(folder_path).name if folder_path else '',
    }
    versions.append(ver)
    save_versions(ws_folder, project, versions)
    return ver


def download_version_zip(ws_folder, project, version_id):
    versions = load_versions(ws_folder, project)
    ver      = next((v for v in versions if v['id'] == version_id), None)
    if not ver:
        return None
    folder = stored_version_folder(ws_folder, project, ver)
    if folder is None:
        return None
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in folder.rglob('*'):
            if f.is_file():
                zf.write(f, f.relative_to(folder.parent))
    buf.seek(0)
    return buf
