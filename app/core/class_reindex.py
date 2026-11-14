"""
Change class IDs ("indices") across a whole project, safely.

A YOLO label line stores only the class ID (`2 0.51 0.40 0.10 0.22`), so moving
a class from ID 2 to ID 0 means rewriting the first token of every line that
uses it, everywhere the project keeps class IDs:

    labels/<name>.txt                    confirmed boxes and polygons
    labels/<name>.suggestions.json       suggested/rejected boxes (class_id)
    prompt_examples.json                 AI Annotate example library (class_id)
    project.json                         the class list itself
    data.yaml                            regenerated if the project has one

NOT touched: Versions/ (immutable snapshots that carry their own data.yaml,
so their numbering stays as it was when they were created) and _backups/.

`mapping` is {old_id: new_id} for the classes that move; every other class
keeps its ID. Validation guarantees the result is a one-to-one renumbering
(no two classes end up with the same ID), so labels are never merged.

Safety:
  * plan() reads everything and changes nothing (the UI's preview).
  * apply() first writes a zip of every file it will change to
    paths.class_id_backups_dir(); then writes each file atomically
    (tmp + os.replace); if any write fails, every file already written is
    restored from memory and the error re-raised. The zip stays as a manual
    undo path either way.
"""
import io
import json
import os
import zipfile
from datetime import datetime
from pathlib import Path

from app.core.paths import (class_id_backups_dir, project_dir, project_meta_file,
                            prompt_examples_file)
from app.core.storage import load_project_meta
from app.core.suggestions import SIDECAR_SUFFIX


class ReindexError(ValueError):
    """The requested mapping is invalid (bad IDs, collisions…)."""


# ── Mapping ──────────────────────────────────────────────────────────────────

def full_mapping(classes: list, mapping: dict) -> dict:
    """Validate `mapping` ({old: new}) against the class list and return the
    complete {old_id: new_id} for every class (identity for the unmoved)."""
    ids = {int(c['id']) for c in classes}
    clean = {}
    for k, v in (mapping or {}).items():
        try:
            old, new = int(k), int(v)
        except (TypeError, ValueError):
            raise ReindexError('Class IDs must be whole numbers.')
        if old not in ids:
            raise ReindexError(f'There is no class with ID {old}.')
        if new < 0:
            raise ReindexError('Class IDs cannot be negative.')
        if new > 9999:
            raise ReindexError('Class ID is too large.')
        clean[old] = new
    full = {cid: clean.get(cid, cid) for cid in ids}
    targets = list(full.values())
    if len(set(targets)) != len(targets):
        dup = sorted({t for t in targets if targets.count(t) > 1})
        raise ReindexError(f'Two classes would share ID {dup[0]}. Swap or shift the other class too.')
    if all(o == n for o, n in full.items()):
        raise ReindexError('Nothing to change: every class keeps its ID.')
    return full


# ── File discovery ───────────────────────────────────────────────────────────

def _label_dirs(pd: Path):
    """Every `labels` folder in the project except immutable Versions/ and
    internal folders (_backups, .thumbs, …)."""
    vdir = pd / 'Versions'
    for root, dirs, _files in os.walk(pd):
        rp = Path(root)
        dirs[:] = [d for d in dirs if not d.startswith(('.', '_'))
                   and (rp / d) != vdir]
        if rp.name == 'labels':
            yield rp


def _remap_label_text(text: str, full: dict, counts: dict):
    """Rewrite the leading class token of each YOLO line; everything else on
    the line (coordinates, polygon points, spacing) stays byte-identical."""
    out, changed = [], False
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        token = stripped.split(None, 1)[0] if stripped.strip() else ''
        try:
            cid = int(float(token)) if token else None
        except ValueError:
            cid = None
        if cid is not None:
            counts[cid] = counts.get(cid, 0) + 1     # every ID seen, incl. orphans
        if cid is not None and cid in full:
            if full[cid] != cid:
                lead = line[:len(line) - len(stripped)]
                line = lead + str(full[cid]) + stripped[len(token):]
                changed = True
        out.append(line)
    return ''.join(out), changed


def _remap_json_class_ids(rows, full: dict):
    changed = False
    for r in rows:
        if isinstance(r, dict) and 'class_id' in r:
            try:
                cid = int(r['class_id'])
            except (TypeError, ValueError):
                continue
            if full.get(cid, cid) != cid:
                r['class_id'] = full[cid]
                changed = True
    return changed


def _plan_files(ws: str, project: str, full: dict):
    """[(path, original_bytes, new_bytes)] for every file that changes, plus
    per-class box counts."""
    pd = project_dir(ws, project)
    edits, counts = [], {}
    for ldir in _label_dirs(pd):
        for f in sorted(ldir.iterdir()):
            if f.suffix == '.txt' and f.is_file():
                raw = f.read_bytes()
                text = raw.decode('utf-8', errors='replace')
                new, changed = _remap_label_text(text, full, counts)
                if changed:
                    edits.append((f, raw, new.encode('utf-8')))
            elif f.name.endswith(SIDECAR_SUFFIX) and f.is_file():
                raw = f.read_bytes()
                try:
                    data = json.loads(raw.decode('utf-8'))
                except ValueError:
                    continue
                if _remap_json_class_ids(data.get('boxes', []) if isinstance(data, dict) else [], full):
                    edits.append((f, raw, json.dumps(data, indent=2).encode('utf-8')))
    ex = prompt_examples_file(ws, project)
    if ex.is_file():
        raw = ex.read_bytes()
        try:
            data = json.loads(raw.decode('utf-8'))
        except ValueError:
            data = None
        rows = data.get('examples', []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        if data is not None and _remap_json_class_ids(rows, full):
            edits.append((ex, raw, json.dumps(data, indent=2).encode('utf-8')))
    return edits, counts


def _check_orphans(full: dict, counts: dict):
    """Refuse to move a class onto an ID that is not a current class but still
    appears in label files (left over from a deleted class): those boxes
    would silently become the moved class."""
    for old, new in full.items():
        if old != new and new not in full and counts.get(new):
            raise ReindexError(
                f'ID {new} is not a current class, but {counts[new]} label line(s) still use it '
                f'(left over from a deleted class). Choose another ID.')


def _new_meta(ws: str, project: str, full: dict):
    meta = load_project_meta(ws, project)
    for c in meta.get('classes', []):
        c['id'] = full.get(int(c['id']), int(c['id']))
    meta['classes'] = sorted(meta.get('classes', []), key=lambda c: c['id'])
    return meta


def _data_yaml_bytes(classes: list) -> bytes:
    import yaml
    max_id = max((c['id'] for c in classes), default=-1)
    names = [''] * (max_id + 1)
    for c in classes:
        names[c['id']] = c['name']
    while names and not names[-1]:
        names.pop()
    return yaml.dump({'names': names, 'nc': len(classes)},
                     default_flow_style=False, allow_unicode=True).encode('utf-8')


# ── Public API ───────────────────────────────────────────────────────────────

def plan(ws: str, project: str, mapping: dict) -> dict:
    """Preview: what would change. Reads only."""
    meta = load_project_meta(ws, project)
    classes = meta.get('classes', [])
    full = full_mapping(classes, mapping)
    edits, counts = _plan_files(ws, project, full)
    _check_orphans(full, counts)
    moved = {o: n for o, n in full.items() if o != n}
    return {
        'mapping': {str(o): n for o, n in sorted(moved.items())},
        'classes': [{'name': c['name'], 'old_id': int(c['id']), 'new_id': full[int(c['id'])]}
                    for c in sorted(classes, key=lambda c: int(c['id']))],
        'files': len(edits),
        'boxes': sum(counts.get(o, 0) for o in moved),
        'boxes_by_class': {str(o): counts.get(o, 0) for o in sorted(moved)},
    }


def apply(ws: str, project: str, mapping: dict) -> dict:
    """Backup, then rewrite every file atomically; roll back on any failure."""
    meta = load_project_meta(ws, project)
    full = full_mapping(meta.get('classes', []), mapping)
    edits, counts = _plan_files(ws, project, full)
    _check_orphans(full, counts)
    pd = project_dir(ws, project)

    new_meta = _new_meta(ws, project, full)
    meta_path = project_meta_file(ws, project)
    edits.append((meta_path, meta_path.read_bytes() if meta_path.exists() else b'',
                  json.dumps(new_meta, indent=2, ensure_ascii=False).encode('utf-8')))
    yaml_path = pd / 'data.yaml'
    if yaml_path.is_file():
        edits.append((yaml_path, yaml_path.read_bytes(), _data_yaml_bytes(new_meta['classes'])))

    # 1) backup zip of every original
    bdir = class_id_backups_dir(ws, project)
    bdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S-%f')
    backup = bdir / f'class_ids_{stamp}.zip'
    with zipfile.ZipFile(backup, 'w', zipfile.ZIP_DEFLATED) as z:
        for path, raw, _new in edits:
            z.writestr(path.relative_to(pd).as_posix(), raw)
        z.writestr('MAPPING.json', json.dumps(
            {'mapping': {str(o): n for o, n in full.items() if o != n},
             'created_utc': stamp}, indent=2))

    # 2) atomic writes, with in-memory rollback
    written = []
    try:
        for path, raw, new in edits:
            tmp = path.with_name(path.name + '.reindex.tmp')
            try:
                tmp.write_bytes(new)
                os.replace(tmp, path)
            finally:
                if tmp.exists():          # failed before/at replace: don't leave it behind
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
            written.append((path, raw))
    except Exception:
        for path, raw in reversed(written):
            try:
                tmp = path.with_name(path.name + '.rollback.tmp')
                tmp.write_bytes(raw)
                os.replace(tmp, path)
            except OSError:
                pass
        raise

    # Encoded AI-Annotate examples are cached in memory keyed by class; drop them.
    try:
        from app.core import prompt_models
        prompt_models.clear_example_cache()
    except Exception:
        pass

    moved = {o: n for o, n in full.items() if o != n}
    return {
        'mapping': {str(o): n for o, n in sorted(moved.items())},
        'classes': new_meta['classes'],
        'files': len(edits),
        'boxes': sum(counts.get(o, 0) for o in moved),
        'backup': backup.relative_to(pd).as_posix(),
    }
