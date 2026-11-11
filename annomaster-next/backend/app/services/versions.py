"""
Dataset versions — immutable snapshots.

A version freezes the CONFIRMED label content of every in-dataset image at
snapshot time (read from `.txt`, never the sidecar), plus the class list and a
data.yaml. Storing the label lines in the manifest makes the snapshot truly
immutable: continuing to annotate, or deleting an image, doesn't alter a version
already taken. Exports can then be built from a version's frozen manifest.
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core import paths
from app.core.yolo import parse_yolo_label
from app.services import datasets, storage


def _class_names(folder: str, project: str) -> list[str]:
    meta = storage.load_project_meta(folder, project)
    names = []
    for c in meta.get('classes', []):
        names.append(c['name'] if isinstance(c, dict) else str(c))
    return names


def _data_yaml(names: list[str]) -> str:
    lines = ['train: images/train', 'val: images/valid', 'test: images/test',
             f'nc: {len(names)}', 'names:']
    lines += [f'  {i}: {n}' for i, n in enumerate(names)]
    return '\n'.join(lines) + '\n'


def create_version(session: Session, folder: str, project: str, workspace_id: int,
                   name: str, note: str = '') -> dict:
    names = _class_names(folder, project)
    manifest = []
    splits = {'train': 0, 'valid': 0, 'test': 0}
    pdir = paths.project_dir(folder, project)
    for img in datasets.dataset_images(session, workspace_id, project):
        lbl = paths.label_path_for_image(pdir / img.rel_path)
        labels = parse_yolo_label(lbl)          # CONFIRMED only (from .txt)
        manifest.append({'rel_path': img.rel_path, 'filename': img.filename,
                         'split': img.split, 'labels': labels})
        if img.split in splits:
            splits[img.split] += 1

    version = {
        'name': name, 'note': note,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'num_images': len(manifest), 'splits': splits,
        'classes': names, 'manifest': manifest,
    }
    all_versions = storage.load_versions(folder, project)
    if any(v['name'] == name for v in all_versions):
        raise ValueError(f'A version named "{name}" already exists')
    all_versions.append(version)
    storage.save_versions(folder, project, all_versions)

    # Write data.yaml into Versions/<name>/ so the on-disk layout matches.
    vdir = paths.versions_dir(folder, project) / name
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / 'data.yaml').write_text(_data_yaml(names), encoding='utf-8')
    return {k: version[k] for k in ('name', 'note', 'created_at', 'num_images', 'splits')}


def list_versions(folder: str, project: str) -> list[dict]:
    # Summary only — drop the heavy per-image manifest.
    return [{k: v[k] for k in ('name', 'note', 'created_at', 'num_images', 'splits')}
            for v in storage.load_versions(folder, project)]


def get_version(folder: str, project: str, name: str) -> dict | None:
    return next((v for v in storage.load_versions(folder, project)
                 if v['name'] == name), None)
