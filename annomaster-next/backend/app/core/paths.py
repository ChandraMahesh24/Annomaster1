"""
Path builder — the ONLY module allowed to construct workspace/project paths.

Ported rule from the original app/core/paths.py: nothing else in the codebase
joins onto WORKSPACE_ROOT by hand. A workspace's on-disk folder name IS its
public_id (WS-XXXXXX). Project-level paths (Active_Work/Completed_Datasets/…)
are added in Phase B1; this A3 slice only needs the workspace level.

    workspace/<WS-XXXXXX>/                       ← workspace_dir
      projects/<project>/                        ← (B1)
        Active_Work/job_<DATETIME>/{images,labels}/
        Completed_Datasets/.../{train,valid,test}/{images,labels}/
        Versions/<name>/
"""
from pathlib import Path

from app.core.config import get_settings


def workspace_root() -> Path:
    return Path(get_settings().workspace_root)


def workspace_dir(folder_name: str) -> Path:
    return workspace_root() / folder_name


def workspace_projects_dir(folder_name: str) -> Path:
    return workspace_dir(folder_name) / 'projects'


def ensure_workspace_dir(folder_name: str) -> Path:
    d = workspace_dir(folder_name)
    d.mkdir(parents=True, exist_ok=True)
    (d / 'projects').mkdir(parents=True, exist_ok=True)
    return d


# ── Project ───────────────────────────────────────────────────────────────────

def project_dir(folder_name: str, project: str) -> Path:
    return workspace_projects_dir(folder_name) / project


def active_work_dir(folder_name: str, project: str) -> Path:
    return project_dir(folder_name, project) / 'Active_Work'


def completed_datasets_dir(folder_name: str, project: str) -> Path:
    return project_dir(folder_name, project) / 'Completed_Datasets'


def versions_dir(folder_name: str, project: str) -> Path:
    return project_dir(folder_name, project) / 'Versions'


def project_meta_file(folder_name: str, project: str) -> Path:
    return project_dir(folder_name, project) / 'project.json'


def uploads_meta_file(folder_name: str, project: str) -> Path:
    return project_dir(folder_name, project) / '_uploads.json'


def versions_meta_file(folder_name: str, project: str) -> Path:
    return project_dir(folder_name, project) / 'versions.json'


# ── Batch (an Active_Work job) ────────────────────────────────────────────────

def batch_job_dir(folder_name: str, project: str, job_name: str) -> Path:
    return active_work_dir(folder_name, project) / job_name


def batch_img_dir(folder_name: str, project: str, job_name: str) -> Path:
    return batch_job_dir(folder_name, project, job_name) / 'images'


def batch_lbl_dir(folder_name: str, project: str, job_name: str) -> Path:
    return batch_job_dir(folder_name, project, job_name) / 'labels'


# ── Label file for an image ───────────────────────────────────────────────────

def label_path_for_image(img_path: Path, create_dir: bool = False) -> Path:
    """
    Derive the YOLO label path from an image path by swapping the `images`
    segment for `labels` and the extension for `.txt` — the exact rule from the
    original. `.../images/a.jpg` → `.../labels/a.txt`.
    """
    parts = list(img_path.parts)
    if 'images' in parts:
        parts[parts.index('images')] = 'labels'
        lp = Path(*parts).with_suffix('.txt')
    else:
        lp = img_path.parent.parent / 'labels' / img_path.with_suffix('.txt').name
    if create_dir:
        lp.parent.mkdir(parents=True, exist_ok=True)
    return lp


def ensure_project_dirs(folder_name: str, project: str) -> None:
    for d in (project_dir(folder_name, project),
              active_work_dir(folder_name, project),
              completed_datasets_dir(folder_name, project),
              versions_dir(folder_name, project)):
        d.mkdir(parents=True, exist_ok=True)
