"""Project lifecycle: create, list, delete, summary, rename/duplicate/move/merge."""
import os
import re
import shutil
import stat
import time
import uuid
from datetime import datetime
from pathlib import Path

from app.core.paths import (project_dir, ensure_project_dirs,
                             project_meta_file, active_work_dir,
                             workspace_projects_dir, label_path_for_image)
from app.core.storage import load_project_meta, save_project_meta
from app.core.media import collect_media, annotated_paths


class ProjectOpError(Exception):
    """A project rename/duplicate/move/merge that cannot proceed. The API layer
    turns this into a 4xx with the message, never a bare 500."""


# Same rule the front-end advertises in the New Project modal.
_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')


def validate_project_name(name: str) -> str:
    """Return the cleaned name, or raise ProjectOpError. Rejects anything that
    could escape the projects dir — this is the only name check before a real
    filesystem move, so it is deliberately strict."""
    name = (name or '').strip()
    if not name:
        raise ProjectOpError('Name required')
    if len(name) > 100:
        raise ProjectOpError('Name too long (max 100 characters)')
    if not _NAME_RE.match(name) or '..' in name:
        raise ProjectOpError(
            'Use letters, numbers, dots, hyphens and underscores only')
    return name


def list_projects(ws_folder: str) -> dict:
    from app.core.paths import workspace_projects_dir
    pd_root = workspace_projects_dir(ws_folder)
    result = {}
    if not pd_root.exists():
        return result
    for p in sorted(pd_root.iterdir()):
        if p.is_dir() and not p.name.startswith('.'):
            result[p.name] = load_project_meta(ws_folder, p.name)
    return result


def get_or_create_project(ws_folder: str, project: str,
                           created_by_id: int = None) -> Path:
    ensure_project_dirs(ws_folder, project)
    mf = project_meta_file(ws_folder, project)
    if not mf.exists():
        meta = {
            'project_id':  str(uuid.uuid4()),   # unique ID per project
            'name':        project,
            'created_by':  created_by_id,
            'created_at':  datetime.utcnow().isoformat(),
            'classes':     [],
            'settings':    {},
        }
        save_project_meta(ws_folder, project, meta)
    return project_dir(ws_folder, project)


def delete_project(ws_folder: str, project: str):
    pd = project_dir(ws_folder, project)
    _release_index(pd)
    if pd.exists() and not _rm_tree(pd):
        raise ProjectOpError(
            f'Could not fully delete "{project}" — a file is still open.')


def get_project_summary(ws_folder: str, project: str) -> dict:
    media = collect_media(ws_folder, project)
    ann   = len(annotated_paths(ws_folder, project))
    pd    = project_dir(ws_folder, project)
    meta  = load_project_meta(ws_folder, project)

    try:
        meta_f = project_meta_file(ws_folder, project)
        src    = meta_f if meta_f.exists() else pd
        mtime  = os.path.getmtime(str(src))
        last_modified = datetime.fromtimestamp(mtime).strftime('%d %b %Y, %H:%M')
    except Exception:
        mtime         = None
        last_modified = '—'

    return {
        'name':          project,
        'project_id':    meta.get('project_id', ''),
        'created_by':    meta.get('created_by'),
        'created_at':    meta.get('created_at', ''),
        'total':         len(media),
        'annotated':     ann,
        'unannotated':   len(media) - ann,
        'progress':      round(ann / len(media) * 100) if media else 0,
        'last_modified': last_modified,
        # Raw epoch seconds alongside the formatted string. The dashboard shows
        # a relative "2h ago" label and sorts by recency, and neither can be
        # derived from the localised '%d %b %Y' text without reparsing it.
        'last_modified_ts': mtime,
        'has_cover':     (pd / 'cover.jpg').exists(),
    }


def _release_index(*dirs):
    """
    Drop open handles on each project's `.media_index.db` before its directory
    is renamed/moved/deleted. The index lives INSIDE the project dir, so a live
    SQLite connection is enough to make the whole operation fail on Windows.
    Imported lazily: db_index is optional infrastructure, and a project without
    one must still be movable.
    """
    try:
        from app.core import db_index
    except Exception:
        return
    for d in dirs:
        try:
            db_index.close_project(d)
        except Exception:
            pass


def _rm_tree(path: Path, tries: int = 5) -> bool:
    """
    Delete a directory tree; return True once it is really gone.

    Windows refuses to unlink a file another process still has open (an indexer
    or AV that touched files written seconds ago is enough), so a single rmtree
    can fail. Retry with a growing pause and clear the read-only bit on the way.

    NEVER call `shutil.rmtree(..., ignore_errors=True)` for these operations:
    it reports success while leaving the tree in place, which is how a "move"
    ends up showing the project in BOTH workspaces.
    """
    def _onerror(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    for i in range(tries):
        if not path.exists():
            return True
        shutil.rmtree(str(path), onerror=_onerror)
        if not path.exists():
            return True
        time.sleep(0.1 * (i + 1))
    return not path.exists()


def _move_tree(src: Path, dst: Path):
    """
    Move a directory, tolerating Windows.

    `os.rename` is the fast path, but on Windows it raises PermissionError
    (WinError 5) when anything still holds a handle inside the tree, and
    `shutil.move`'s own fallback re-raises rather than recovering. So fall back
    to copy-then-delete. Observed for real when moving a project that had just
    been created by duplicate_project().

    If the copy succeeds but the original cannot be removed, the copy is rolled
    back and this raises — leaving the project in one place is the only safe
    outcome. Half-moving it would show it in two workspaces at once.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(str(src), str(dst))
        return
    except OSError:
        pass

    shutil.copytree(str(src), str(dst), dirs_exist_ok=True)
    if not _rm_tree(src):
        _rm_tree(dst)
        raise ProjectOpError(
            f'Could not remove "{src.name}" after copying it — a file is still '
            'open. Close anything using the project and try again.')


# ══ Rename / duplicate / move / merge ═════════════════════════════════════════
# All four move real directories, so each one validates the destination BEFORE
# touching anything and raises ProjectOpError rather than half-completing.
# The caller (app/api/projects.py) is responsible for the matching DB row
# updates — Image / UploadBatch / Assignment / AnnotationLock / AuditLog all
# carry a `project` string that must follow the directory.

def rename_project(ws_folder: str, old: str, new: str) -> str:
    """Rename in place. `rel_path` on Image rows is relative to the project dir,
    so nothing inside the tree changes — only the directory and project.json."""
    new = validate_project_name(new)
    if new == old:
        return new
    src = project_dir(ws_folder, old)
    dst = project_dir(ws_folder, new)
    if not src.exists():
        raise ProjectOpError(f'Project "{old}" not found')
    if dst.exists():
        raise ProjectOpError(f'A project named "{new}" already exists')

    _release_index(src)
    _move_tree(src, dst)
    meta = load_project_meta(ws_folder, new)
    meta['name'] = new
    save_project_meta(ws_folder, new, meta)
    return new


def duplicate_project(ws_folder: str, src_name: str, new_name: str) -> str:
    """
    Full copy: images, labels, datasets, versions, classes and settings. The
    copy gets a FRESH project_id — project_id identifies one project, and two
    projects sharing it would confuse anything keyed on it.
    """
    new_name = validate_project_name(new_name)
    src = project_dir(ws_folder, src_name)
    dst = project_dir(ws_folder, new_name)
    if not src.exists():
        raise ProjectOpError(f'Project "{src_name}" not found')
    if dst.exists():
        raise ProjectOpError(f'A project named "{new_name}" already exists')

    _release_index(src)
    shutil.copytree(str(src), str(dst))
    meta = load_project_meta(ws_folder, new_name)
    meta['project_id'] = str(uuid.uuid4())
    meta['name']       = new_name
    meta['created_at'] = datetime.utcnow().isoformat()
    save_project_meta(ws_folder, new_name, meta)
    return new_name


def move_project(src_ws: str, project: str, dst_ws: str,
                 new_name: str = None) -> str:
    """
    Move a project directory to another workspace. Classes travel with it in
    project.json, so class indices in the label files stay correct — unlike a
    merge, nothing has to be remapped.
    """
    name = validate_project_name(new_name or project)
    if src_ws == dst_ws and name == project:
        raise ProjectOpError('Project is already in that workspace')

    src = project_dir(src_ws, project)
    dst = project_dir(dst_ws, name)
    if not src.exists():
        raise ProjectOpError(f'Project "{project}" not found')
    if dst.exists():
        raise ProjectOpError(
            f'The target workspace already has a project named "{name}"')

    _release_index(src)
    workspace_projects_dir(dst_ws).mkdir(parents=True, exist_ok=True)
    _move_tree(src, dst)
    meta = load_project_meta(dst_ws, name)
    meta['name'] = name
    save_project_meta(dst_ws, name, meta)
    return name


def merge_project(ws_folder: str, src_name: str, dst_name: str) -> dict:
    """
    Merge `src_name` INTO `dst_name`, then delete the source.

    ⚠️ The load-bearing part is class-index remapping. A YOLO .txt line starts
    with a class INDEX; the two projects have independent class lists, so
    "2" may mean `sack` in the source and `carton_box` in the target. Every
    moved label file is rewritten through the remap, and the target's class
    list gains any class the source had and it didn't. Without this the merge
    would silently relabel every box it touched.

    Job folders keep their names (`job_<DATETIME>`); a collision gets a
    `__<n>` suffix rather than overwriting, so no images are lost.

    Returns {jobs, images, classes_added} for the caller to report/audit.
    """
    from app.core.yolo import merge_classes_and_remap, remap_label_file

    if src_name == dst_name:
        raise ProjectOpError('Cannot merge a project into itself')
    src = project_dir(ws_folder, src_name)
    dst = project_dir(ws_folder, dst_name)
    if not src.exists():
        raise ProjectOpError(f'Project "{src_name}" not found')
    if not dst.exists():
        raise ProjectOpError(f'Project "{dst_name}" not found')

    # Build the source's classes as an index-ordered list (position = class id,
    # holes for deleted ids) — that is the shape merge_classes_and_remap wants.
    src_classes = load_project_meta(ws_folder, src_name).get('classes', [])
    before      = len(load_project_meta(ws_folder, dst_name).get('classes', []))
    if src_classes:
        size  = max(c['id'] for c in src_classes) + 1
        names = [''] * size
        for c in src_classes:
            names[c['id']] = c['name']
        remap = merge_classes_and_remap(ws_folder, dst_name, names)
    else:
        remap = {}
    after = len(load_project_meta(ws_folder, dst_name).get('classes', []))

    _release_index(src, dst)

    moved_jobs, moved_imgs, renamed = [], 0, {}
    src_active = active_work_dir(ws_folder, src_name)
    dst_active = active_work_dir(ws_folder, dst_name)
    dst_active.mkdir(parents=True, exist_ok=True)

    if src_active.exists():
        for job in sorted(p for p in src_active.iterdir() if p.is_dir()):
            target = dst_active / job.name
            n = 1
            while target.exists():
                target = dst_active / f'{job.name}__{n}'
                n += 1
            if target.name != job.name:
                renamed[job.name] = target.name
            _move_tree(job, target)
            moved_jobs.append(target.name)

            # Rewrite class indices in every label that came across.
            lbl_dir = target / 'labels'
            if lbl_dir.exists():
                for txt in lbl_dir.glob('*.txt'):
                    remap_label_file(txt, remap)
            img_dir = target / 'images'
            if img_dir.exists():
                moved_imgs += sum(1 for _ in img_dir.iterdir() if _.is_file())

    # Completed_Datasets are split into train/valid/test; merge split-by-split
    # so an already-built dataset isn't reshuffled.
    src_done = src / 'Completed_Datasets'
    if src_done.exists():
        for job in sorted(p for p in src_done.iterdir() if p.is_dir()):
            target = dst / 'Completed_Datasets' / job.name
            n = 1
            while target.exists():
                target = dst / 'Completed_Datasets' / f'{job.name}__{n}'
                n += 1
            _move_tree(job, target)
            for lbl_dir in target.rglob('labels'):
                for txt in lbl_dir.glob('*.txt'):
                    remap_label_file(txt, remap)

    # Versions are immutable snapshots with their own data.yaml naming their
    # own classes; remapping them would break that self-consistency, so they
    # are deliberately NOT carried over. The source dir is removed last — and
    # a failure here is reported, not swallowed, or the merged-away project
    # keeps showing up in the grid with its contents already gone.
    if not _rm_tree(src):
        raise ProjectOpError(
            f'Merged into "{dst_name}", but "{src_name}" could not be removed '
            '— a file is still open. Delete it manually.')

    return {'jobs': moved_jobs, 'images': moved_imgs,
            'classes_added': after - before, 'renamed_jobs': renamed}
