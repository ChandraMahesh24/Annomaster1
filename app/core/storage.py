"""
JSON metadata read/write.

Uses atomic write (write temp → rename) which is safe for single-server
deployments. The temp→rename approach prevents partial reads.

_FileLock is only used for _uploads.json which is written by concurrent
upload requests. project.json and versions.json are written rarely.
"""
import json
import os
import time
import uuid
from pathlib import Path

DEFAULT_PALETTE = [
    [255,59,59],[255,142,30],[255,211,30],[74,222,128],[34,197,225],
    [99,102,241],[168,85,247],[236,72,153],[20,184,166],[249,115,22],
    [139,92,246],[6,182,212],[132,204,22],[245,158,11],[239,68,68],
]


def _atomic_write(path: Path, data):
    """Write JSON atomically: write to .tmp then rename → readers never see partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f'.{uuid.uuid4().hex[:8]}.tmp')
    try:
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
        os.replace(str(tmp), str(path))
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def load_json(path: Path, default=None):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            pass
    return default if default is not None else {}


def save_json(path: Path, data):
    _atomic_write(path, data)


# ── Project metadata ──────────────────────────────────────────────────────────

def load_project_meta(ws_folder: str, project: str) -> dict:
    from app.core.paths import project_meta_file
    return load_json(project_meta_file(ws_folder, project),
                     {'classes': [], 'settings': {}})


def save_project_meta(ws_folder: str, project: str, data: dict):
    from app.core.paths import project_meta_file
    _atomic_write(project_meta_file(ws_folder, project), data)


# ── Upload batches (uses OS-level lock for concurrent upload requests) ─────────

class _SimpleLock:
    """Fast advisory lock via O_CREAT|O_EXCL — atomic on all major filesystems."""
    def __init__(self, path: Path):
        self._lock = path.with_suffix(path.suffix + '.lock')

    def __enter__(self):
        deadline = time.monotonic() + 8.0
        delay    = 0.01
        while True:
            try:
                fd = os.open(str(self._lock),
                             os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return self
            except FileExistsError:
                if time.monotonic() > deadline:
                    # Stale lock — remove and proceed
                    try: self._lock.unlink(missing_ok=True)
                    except Exception: pass
                    return self
                time.sleep(delay)
                delay = min(delay * 1.8, 0.2)

    def __exit__(self, *_):
        try: self._lock.unlink(missing_ok=True)
        except Exception: pass


def load_uploads(ws_folder: str, project: str) -> list:
    from app.core.paths import uploads_meta_file
    return load_json(uploads_meta_file(ws_folder, project), [])


def save_uploads(ws_folder: str, project: str, data: list):
    from app.core.paths import uploads_meta_file
    p = uploads_meta_file(ws_folder, project)
    with _SimpleLock(p):
        _atomic_write(p, data)


# ── Versions ──────────────────────────────────────────────────────────────────

def load_versions(ws_folder: str, project: str) -> list:
    from app.core.paths import versions_meta_file
    return load_json(versions_meta_file(ws_folder, project), [])


def save_versions(ws_folder: str, project: str, data: list):
    from app.core.paths import versions_meta_file
    _atomic_write(versions_meta_file(ws_folder, project), data)


# ── Upload ID ─────────────────────────────────────────────────────────────────

def next_upload_id(ws_folder: str, project: str) -> int:
    batches = load_uploads(ws_folder, project)
    return max((b['upload_id'] for b in batches), default=0) + 1
