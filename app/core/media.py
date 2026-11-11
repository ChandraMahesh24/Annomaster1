"""
Image discovery, thumbnail generation, and media collection.

collect_media() and annotated_paths() now query the SQLite index
instead of scanning the filesystem. Falls back to filesystem scan
if the index doesn't exist (first run on existing projects).
"""
import io
import hashlib
from pathlib import Path
from PIL import Image

ALLOWED_IMG = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp'}
THUMB_SIZE  = (320, 240)


def _ensure_index(ws_folder: str, project: str):
    """Build the SQLite index if it doesn't exist or is empty."""
    from app.core.paths import project_dir, active_work_dir
    from app.core import db_index
    pd  = project_dir(ws_folder, project)
    aw  = active_work_dir(ws_folder, project)
    db  = db_index._db_path(pd)
    if not db.exists():
        db_index.rebuild_from_filesystem(pd, aw)
    else:
        # Quick check: if DB is empty but filesystem has images, rebuild
        conn = db_index._get_conn(pd)
        count = conn.execute('SELECT COUNT(*) FROM media').fetchone()[0]
        if count == 0 and aw.exists():
            db_index.rebuild_from_filesystem(pd, aw)


def collect_media(ws_folder: str, project: str) -> list:
    """
    Return all images in Active_Work.
    Uses SQLite index — always 2ms regardless of project size.
    Falls back to filesystem scan if index is unavailable.
    """
    try:
        _ensure_index(ws_folder, project)
        from app.core.paths import project_dir
        from app.core import db_index
        pd = project_dir(ws_folder, project)
        return db_index.get_all_paths(pd)
    except Exception:
        return _collect_media_filesystem(ws_folder, project)


def _collect_media_filesystem(ws_folder: str, project: str) -> list:
    """Fallback: original filesystem-based scan."""
    from app.core.paths import active_work_dir, project_dir
    aw = active_work_dir(ws_folder, project)
    pd = project_dir(ws_folder, project)
    result = []
    if not aw.exists():
        return result
    for job in sorted(aw.iterdir()):
        if not job.is_dir():
            continue
        img_dir = job / 'images'
        if not img_dir.exists():
            continue
        for img in sorted(img_dir.iterdir()):
            if img.suffix.lower() in ALLOWED_IMG:
                result.append({
                    'path':   str(img.relative_to(pd)),
                    'name':   img.name,
                    'job':    job.name,
                    'split':  None,
                    'folder': 'Active_Work',
                })
    return result


def annotated_paths(ws_folder: str, project: str) -> list:
    """
    Return paths of all annotated images.
    Uses SQLite index — always 1ms.
    """
    try:
        _ensure_index(ws_folder, project)
        from app.core.paths import project_dir
        from app.core import db_index
        pd   = project_dir(ws_folder, project)
        conn = db_index._get_conn(pd)
        rows = conn.execute(
            'SELECT path FROM media WHERE is_annotated = 1'
        ).fetchall()
        return [r['path'] for r in rows]
    except Exception:
        return _annotated_paths_filesystem(ws_folder, project)


def _annotated_paths_filesystem(ws_folder: str, project: str) -> list:
    """Fallback: original filesystem-based annotation check."""
    from app.core.paths import active_work_dir, project_dir
    from app.core.yolo import is_valid_annotation_file
    aw = active_work_dir(ws_folder, project)
    pd = project_dir(ws_folder, project)
    result = []
    if not aw.exists():
        return result
    for job in aw.iterdir():
        if not job.is_dir():
            continue
        lbl_dir = job / 'labels'
        img_dir = job / 'images'
        if not lbl_dir.exists():
            continue
        for lbl in lbl_dir.iterdir():
            if lbl.suffix != '.txt':
                continue
            if is_valid_annotation_file(lbl):
                for ext in ALLOWED_IMG:
                    img = img_dir / (lbl.stem + ext)
                    if img.exists():
                        result.append(str(img.relative_to(pd)))
                        break
    return result


def make_thumbnail(img_path: Path) -> bytes:
    with Image.open(img_path) as im:
        im.thumbnail(THUMB_SIZE, Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format='JPEG', quality=90)
        return buf.getvalue()


def get_or_make_thumbnail(img_path: Path, cache_root: Path) -> Path:
    cache_root.mkdir(exist_ok=True)
    key   = hashlib.md5(f"{img_path}:{THUMB_SIZE[0]}x{THUMB_SIZE[1]}".encode()).hexdigest()
    cache = cache_root / (key + '.jpg')
    if not cache.exists():
        cache.write_bytes(make_thumbnail(img_path))
    return cache
