"""
Workspace-aware path builder.

Storage layout (NEVER change this):
  workspace/<ws_folder>/projects/<project>/
    Active_Work/
      job_DATETIME/
        images/    ← uploaded images
        labels/    ← YOLO .txt annotation files
    Completed_Datasets/
      job_DATETIME/
        train/images/   train/labels/
        valid/images/   valid/labels/
        test/images/    test/labels/
        data.yaml
        dataset.json
    Versions/
      <name>/
        images/train|val|test/
        labels/train|valid|test/
        data.yaml  README.md
    project.json
    versions.json
    _uploads.json
"""
from pathlib import Path, PureWindowsPath
from flask import current_app
from werkzeug.exceptions import BadRequest


def resolve_project_path(base: Path, relative: str) -> Path:
    """Resolve an untrusted relative path, rejecting traversal and symlink escapes."""
    if not isinstance(relative, str) or not relative or '\x00' in relative:
        raise BadRequest('A nonempty relative path is required')
    win = PureWindowsPath(relative)
    if win.drive or win.root:
        raise BadRequest('Absolute paths are not allowed')
    parts = relative.replace('\\', '/').split('/')
    if any(p in ('', '.', '..') or ':' in p or p.endswith((' ', '.')) for p in parts):
        raise BadRequest('Invalid relative path')
    root = base.resolve()
    try:
        candidate = root.joinpath(*parts).resolve()
    except (OSError, ValueError, RuntimeError) as exc:
        raise BadRequest('Invalid relative path') from exc
    if not candidate.is_relative_to(root) or candidate == root:
        raise BadRequest('Path must stay inside the project')
    return candidate


def project_label_path(base: Path, relative: str) -> Path:
    """Validate both image and derived label paths, including label symlinks."""
    image = resolve_project_path(base, relative)
    label = label_path_for_image(image)
    label = resolve_project_path(base, label.relative_to(base.resolve()).as_posix())
    sidecar = label.with_suffix('.suggestions.json')
    resolve_project_path(base, sidecar.relative_to(base.resolve()).as_posix())
    return label


# ── Workspace ──────────────────────────────────────────────────────────────────

def workspace_root() -> Path:
    return Path(current_app.config['WORKSPACE_ROOT'])


def workspace_dir(folder_name: str) -> Path:
    return workspace_root() / folder_name


def workspace_projects_dir(folder_name: str) -> Path:
    return workspace_dir(folder_name) / 'projects'


# ── Project ────────────────────────────────────────────────────────────────────

def project_dir(ws_folder: str, project: str) -> Path:
    if not isinstance(project, str) or '/' in project or '\\' in project:
        raise BadRequest('Invalid project name')
    return resolve_project_path(workspace_projects_dir(ws_folder), project)


def active_work_dir(ws_folder: str, project: str) -> Path:
    return project_dir(ws_folder, project) / 'Active_Work'


def completed_datasets_dir(ws_folder: str, project: str) -> Path:
    return project_dir(ws_folder, project) / 'Completed_Datasets'


def versions_dir(ws_folder: str, project: str) -> Path:
    return project_dir(ws_folder, project) / 'Versions'


def project_meta_file(ws_folder: str, project: str) -> Path:
    return project_dir(ws_folder, project) / 'project.json'


def versions_meta_file(ws_folder: str, project: str) -> Path:
    return project_dir(ws_folder, project) / 'versions.json'


def uploads_meta_file(ws_folder: str, project: str) -> Path:
    return project_dir(ws_folder, project) / '_uploads.json'


def prompt_examples_file(ws_folder: str, project: str) -> Path:
    """
    The project's box-prompt example library (AI Annotate → Box prompt).

    Example boxes are PROMPTS, not annotations: they live here, never in a
    label file, so they cannot reach an export. Per project, because each
    project teaches its own classes. See core/box_examples.py.
    """
    return project_dir(ws_folder, project) / 'prompt_examples.json'


def class_id_backups_dir(ws_folder: str, project: str) -> Path:
    """
    Zips written by core/class_reindex.py BEFORE it rewrites class IDs: every
    label/sidecar/meta file it is about to change, at its project-relative path.
    Unzip over the project folder to undo a Change-ID operation.
    """
    return project_dir(ws_folder, project) / '_backups' / 'class_ids'


def tags_meta_file(ws_folder: str, project: str) -> Path:
    """
    Tags that have no record of their own to live on.

    Batch tags ride inside `_uploads.json` next to the batch they describe, so
    they move and delete with it. Datasets have no such record — they are
    derived either from DB rows (`db_<id>`) or from a Completed_Datasets folder
    — so their tags are kept here, keyed by dataset_id.
    """
    return project_dir(ws_folder, project) / '_tags.json'


# ── Batch (Active Work job) ────────────────────────────────────────────────────

def batch_job_dir(ws_folder: str, project: str, job_name: str) -> Path:
    return active_work_dir(ws_folder, project) / job_name


def batch_img_dir(ws_folder: str, project: str, job_name: str) -> Path:
    return batch_job_dir(ws_folder, project, job_name) / 'images'


def batch_lbl_dir(ws_folder: str, project: str, job_name: str) -> Path:
    return batch_job_dir(ws_folder, project, job_name) / 'labels'


# ── Label from image path ──────────────────────────────────────────────────────

def label_path_for_image(img_path: Path, create_dir: bool = False) -> Path:
    """
    Derive the label path from an image path by replacing 'images' → 'labels'
    and changing the extension to .txt.

    img:   .../Active_Work/job_X/images/photo.jpg
    label: .../Active_Work/job_X/labels/photo.txt

    create_dir=True  → mkdir the labels dir (use on write)
    create_dir=False → do NOT mkdir (use on read — avoids unnecessary I/O)
    """
    parts = list(img_path.parts)
    if 'images' in parts:
        idx = parts.index('images')
        parts[idx] = 'labels'
        lp = Path(*parts).with_suffix('.txt')
        if create_dir:
            lp.parent.mkdir(parents=True, exist_ok=True)
        return lp
    # fallback
    lp = img_path.parent.parent / 'labels' / img_path.with_suffix('.txt').name
    if create_dir:
        lp.parent.mkdir(parents=True, exist_ok=True)
    return lp


# ── Ensure project dirs exist ──────────────────────────────────────────────────

def ensure_project_dirs(ws_folder: str, project: str):
    for d in [
        project_dir(ws_folder, project),
        active_work_dir(ws_folder, project),
        completed_datasets_dir(ws_folder, project),
        versions_dir(ws_folder, project),
    ]:
        d.mkdir(parents=True, exist_ok=True)
