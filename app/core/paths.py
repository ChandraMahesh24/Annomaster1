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
from pathlib import Path
from flask import current_app


# ── Workspace ──────────────────────────────────────────────────────────────────

def workspace_root() -> Path:
    return Path(current_app.config['WORKSPACE_ROOT'])


def workspace_dir(folder_name: str) -> Path:
    return workspace_root() / folder_name


def workspace_projects_dir(folder_name: str) -> Path:
    return workspace_dir(folder_name) / 'projects'


# ── Project ────────────────────────────────────────────────────────────────────

def project_dir(ws_folder: str, project: str) -> Path:
    return workspace_projects_dir(ws_folder) / project


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
