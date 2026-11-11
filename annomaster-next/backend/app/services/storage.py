"""
JSON metadata on disk — project.json, _uploads.json, versions.json.

Projects are NOT a DB table (ported decision): a project is a directory plus a
project.json holding its classes + settings. Writes are atomic (temp file →
os.replace) so a crash mid-write can't corrupt the file.
"""
import json
import os
import uuid
from pathlib import Path

from app.core import paths

# Default class colour palette (ported from the original DEFAULT_PALETTE).
DEFAULT_PALETTE = [
    [255, 59, 59], [255, 142, 30], [255, 211, 30], [74, 222, 128], [34, 197, 225],
    [99, 102, 241], [168, 85, 247], [236, 72, 153], [20, 184, 166], [249, 115, 22],
]


def _atomic_write(path: Path, data) -> None:
    from app.core.fsutil import atomic_write
    atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False))


def _load(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            pass
    return default


# ── project.json ──────────────────────────────────────────────────────────────

def load_project_meta(folder: str, project: str) -> dict:
    return _load(paths.project_meta_file(folder, project),
                 {'classes': [], 'settings': {}})


def save_project_meta(folder: str, project: str, meta: dict) -> None:
    _atomic_write(paths.project_meta_file(folder, project), meta)


def get_or_create_project(folder: str, project: str) -> dict:
    """Ensure the project's dirs + project.json exist; return its meta."""
    paths.ensure_project_dirs(folder, project)
    mf = paths.project_meta_file(folder, project)
    if not mf.exists():
        meta = {'classes': [], 'settings': {}}
        _atomic_write(mf, meta)
        return meta
    return load_project_meta(folder, project)


# ── _uploads.json (batch list on disk, mirrors the DB batch rows) ────────────

def load_uploads(folder: str, project: str) -> list:
    return _load(paths.uploads_meta_file(folder, project), [])


def save_uploads(folder: str, project: str, data: list) -> None:
    _atomic_write(paths.uploads_meta_file(folder, project), data)


def next_upload_id(folder: str, project: str) -> int:
    batches = load_uploads(folder, project)
    return max((b.get('upload_id', 0) for b in batches), default=0) + 1


# ── versions.json (immutable snapshot manifests) ─────────────────────────────

def load_versions(folder: str, project: str) -> list:
    return _load(paths.versions_meta_file(folder, project), [])


def save_versions(folder: str, project: str, data: list) -> None:
    _atomic_write(paths.versions_meta_file(folder, project), data)
