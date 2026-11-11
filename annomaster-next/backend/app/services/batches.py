"""
Batch helpers — shared by every upload path (single/folder/zip/video).

A "batch" is one upload operation: an Active_Work/job_<DATETIME>/ dir on disk,
a row in `upload_batches`, and an entry in `_uploads.json`. Kept in one place so
all four upload sources register images identically — the original had this
logic copy-pasted per endpoint, which is how video extraction ended up
registering frames NOWHERE.
"""
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core import paths
from app.models.upload_batch import UploadBatch
from app.services import storage
from app.services.media import (
    ALLOWED_IMG, find_duplicate, md5_bytes, register_image,
)


def new_job_name() -> str:
    now = datetime.now()
    return now.strftime('job_%Y-%m-%d_%H-%M-%S_') + f'{now.microsecond // 1000:03d}'


# ── Importing a labelled dataset: class merge + label remap ───────────────────
# Ported verbatim from the original app/api/uploads.py. When a YOLO folder or ZIP
# arrives it carries its OWN class ordering (data.yaml `names:` / classes.txt).
# Those source indices almost never line up with the project's existing class
# ids, so every label file's class column must be rewritten — otherwise a "0" that
# meant "person" in the source silently becomes whatever class 0 is in the project.

def class_names_from_yaml(data: bytes) -> list[str]:
    """Parse a data.yaml/data.yml `names:` list. Tolerates a dict {0: 'a', 1: 'b'}
    or a bare list. Returns [] on any parse error (matches the original)."""
    try:
        import yaml
        names = yaml.safe_load(data.decode('utf-8', errors='ignore')).get('names', [])
    except Exception:
        return []
    if isinstance(names, dict):                       # ultralytics {idx: name}
        return [names[k] for k in sorted(names, key=lambda x: int(x))]
    return list(names) if isinstance(names, list) else []


def class_names_from_txt(data: bytes) -> list[str]:
    """Parse classes.txt — one class name per line, order = index."""
    return [ln.strip() for ln in data.decode('utf-8', errors='ignore').splitlines()
            if ln.strip()]


def merge_classes_and_remap(folder: str, project: str,
                            incoming_names: list) -> dict:
    """
    Merge `incoming_names` (ordered, from the source dataset) into the project's
    class list WITHOUT reusing deleted ids, and return {source_index → project_id}.
    New names get the next id (max+1) and a palette colour. Verbatim port of the
    original's _merge_classes_and_remap.
    """
    if not incoming_names:
        return {}
    meta = storage.load_project_meta(folder, project)
    classes = meta.get('classes', [])
    name_to_id = {c['name']: c['id'] for c in classes}
    next_id = (max(c['id'] for c in classes) + 1) if classes else 0

    remap: dict[int, int] = {}
    changed = False
    for src_idx, name in enumerate(incoming_names):
        name = (name or '').strip()
        if not name:
            continue
        if name in name_to_id:
            remap[src_idx] = name_to_id[name]
        else:
            color = storage.DEFAULT_PALETTE[next_id % len(storage.DEFAULT_PALETTE)]
            classes.append({'id': next_id, 'name': name, 'color': color})
            name_to_id[name] = next_id
            remap[src_idx] = next_id
            next_id += 1
            changed = True
    if changed:
        meta['classes'] = classes
        storage.save_project_meta(folder, project, meta)
    return remap


def remap_label_bytes(data: bytes, remap: dict) -> bytes:
    """
    Rewrite a YOLO .txt's class column using `remap` (source_id → project_id),
    preserving coordinates exactly and skipping unparseable lines. Operates on
    bytes (the label hasn't been written to disk yet in the port). Verbatim port
    of the original's _remap_label_file logic.
    """
    if not remap:
        return data
    text = data.decode('utf-8', errors='ignore')
    lines_out = []
    changed = False
    for line in text.splitlines():
        parts = line.strip().split()
        if not parts:
            lines_out.append('')
            continue
        try:
            src_id = int(float(parts[0]))
        except (ValueError, IndexError):
            lines_out.append(line)
            continue
        if src_id in remap and remap[src_id] != src_id:
            parts[0] = str(remap[src_id])
            lines_out.append(' '.join(parts))
            changed = True
        else:
            lines_out.append(line)
    if not changed:
        return data
    return ('\n'.join(lines_out) + ('\n' if lines_out else '')).encode('utf-8')


def safe_filename(filename: str, max_len: int = 100) -> str:
    from pathlib import Path
    p = Path(filename)
    stem = re.sub(r'[^\w\-.]', '_', p.stem)[: max_len - len(p.suffix)]
    return stem + p.suffix


def create_batch(session: Session, folder: str, project: str, workspace_id: int,
                 source: str, uploader_id: int) -> dict:
    """Make the job dirs, the DB row, and the _uploads.json entry together."""
    storage.get_or_create_project(folder, project)
    job_name = new_job_name()
    paths.batch_img_dir(folder, project, job_name).mkdir(parents=True, exist_ok=True)
    paths.batch_lbl_dir(folder, project, job_name).mkdir(parents=True, exist_ok=True)

    ub = UploadBatch(workspace_id=workspace_id, project=project,
                     batch_name=job_name, source=source, uploaded_by=uploader_id)
    session.add(ub)
    session.flush()   # need ub.id

    batch = {
        'upload_id': storage.next_upload_id(folder, project),
        'job_name': job_name, 'source': source, 'batch_db_id': ub.id,
        'cls_names': [], 'in_dataset': False,
        'uploaded_at': datetime.now(timezone.utc).isoformat(),
        'uploaded_by': uploader_id,
    }
    batches = storage.load_uploads(folder, project)
    batches.append(batch)
    storage.save_uploads(folder, project, batches)
    return batch


def save_and_register(session: Session, *, folder: str, project: str,
                      workspace_id: int, batch: dict, uploader_id: int,
                      filename: str, data: bytes, is_annotated: bool = False) -> str:
    """
    Write one image to the batch and register it — UNLESS its md5 already exists
    in this project (then it's a duplicate: not written, not rowed → no drift).
    Returns 'saved' | 'duplicate'.
    """
    md5 = md5_bytes(data)
    if find_duplicate(session, workspace_id, project, md5):
        return 'duplicate'

    name = safe_filename(filename)
    img_dir = paths.batch_img_dir(folder, project, batch['job_name'])
    dest = img_dir / name
    # collision on name (different content, same name) → suffix it
    counter = 2
    while dest.exists():
        dest = img_dir / f'{dest.stem}_{counter}{dest.suffix}'
        counter += 1
    dest.write_bytes(data)

    rel = str(dest.relative_to(paths.project_dir(folder, project))).replace('\\', '/')
    register_image(session, workspace_id=workspace_id, project=project,
                   batch_id=batch['batch_db_id'], filename=dest.name,
                   rel_path=rel, md5=md5, uploaded_by=uploader_id,
                   is_annotated=is_annotated)
    return 'saved'


def register_on_disk(session: Session, *, folder: str, project: str,
                     workspace_id: int, batch: dict, uploader_id: int,
                     file_path):
    """
    Register a file ALREADY on disk (e.g. an ffmpeg-extracted frame) without
    re-writing it. Returns the new Image row, or None if it was a duplicate
    (md5 already in project) — in which case the file is removed so extraction
    can't leave dupes behind.
    """
    from pathlib import Path
    file_path = Path(file_path)
    md5 = md5_bytes(file_path.read_bytes())
    if find_duplicate(session, workspace_id, project, md5):
        file_path.unlink(missing_ok=True)
        return None
    rel = str(file_path.relative_to(paths.project_dir(folder, project))).replace('\\', '/')
    return register_image(session, workspace_id=workspace_id, project=project,
                          batch_id=batch['batch_db_id'], filename=file_path.name,
                          rel_path=rel, md5=md5, uploaded_by=uploader_id)
