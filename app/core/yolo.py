"""YOLO label file read/write and validation.

write_yolo_label() uses an atomic temp-file + rename pattern so readers
never see a partially-written file, even if the process is killed mid-write.
"""
import math
import os
import uuid
from pathlib import Path


def validate_boxes(boxes):
    """Reject invalid labels before any existing file is changed."""
    if not isinstance(boxes, list):
        raise ValueError('bboxes must be a list')
    for b in boxes:
        try:
            cid = b['class_id']
            if isinstance(cid, bool) or not isinstance(cid, (int, float)) or not math.isfinite(cid) or cid < 0 or int(cid) != cid:
                raise ValueError('class_id must be a nonnegative integer')
            if b.get('type', 'bbox') == 'polygon':
                pts = b['points']
                if not isinstance(pts, list) or len(pts) < 3:
                    raise ValueError('Polygons require at least three points')
                vals = [p[k] for p in pts for k in ('x', 'y')]
            elif b.get('type', 'bbox') == 'bbox':
                vals = [b[k] for k in ('x_center', 'y_center', 'width', 'height')]
                if any(round(b[k], 6) <= 0 for k in ('width', 'height')):
                    raise ValueError('Box dimensions must remain positive at YOLO precision')
            else:
                raise ValueError('Unknown annotation type')
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in vals):
                raise ValueError('Coordinates must be finite numbers between 0 and 1')
        except (KeyError, TypeError, AttributeError, OverflowError) as exc:
            raise ValueError('Invalid annotation shape or coordinates') from exc


def is_valid_annotation_file(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        content = path.read_text(encoding='utf-8', errors='ignore').strip()
    except OSError:
        return False
    if not content or content == '__null__':  # empty or legacy null marker
        return False
    for line in content.splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        if len(parts) == 5 or (len(parts) > 5 and len(parts) % 2 == 1):
            try:
                vals = [float(x) for x in parts]
                if vals[0] < 0 or not float(vals[0]).is_integer():
                    continue
                coords = vals[1:]
                if all(0.0 <= v <= 1.0 and not (v != v) for v in coords):
                    if len(parts) == 5 and (coords[2] <= 0 or coords[3] <= 0):
                        continue
                    return True
            except (ValueError, IndexError):
                continue
    return False


def parse_yolo_label(lbl_path: Path) -> list:
    bboxes = []
    if not lbl_path.exists():
        return bboxes
    for line in lbl_path.read_text(encoding='utf-8', errors='ignore').splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        try:
            class_value = float(parts[0])
            if not math.isfinite(class_value) or class_value < 0 or not class_value.is_integer():
                continue
            if len(parts) == 5:
                cls_id = int(float(parts[0]))
                xc, yc, w, h = map(float, parts[1:])
                if not all(0.0 <= v <= 1.0 for v in [xc, yc, w, h]):
                    continue
                if cls_id < 0 or w <= 0 or h <= 0:
                    continue
                bboxes.append({'class_id': cls_id, 'type': 'bbox',
                               'x_center': xc, 'y_center': yc,
                               'width': w, 'height': h})
            elif len(parts) > 5 and len(parts) % 2 == 1:
                cls_id = int(float(parts[0]))
                pts = [{'x': float(parts[i]), 'y': float(parts[i + 1])}
                       for i in range(1, len(parts), 2)]
                if all(0.0 <= p['x'] <= 1.0 and 0.0 <= p['y'] <= 1.0 for p in pts):
                    bboxes.append({'class_id': cls_id, 'type': 'polygon', 'points': pts})
        except (ValueError, IndexError):
            continue
    return bboxes


def write_yolo_label(lbl_path: Path, bboxes: list):
    """
    Write YOLO annotation file atomically.

    Strategy: build content → write to a UUID-named .tmp sibling → os.replace()
    into the final path.  os.replace() is atomic on POSIX and on Windows (NTFS)
    so readers always see either the old complete file or the new complete file,
    never a partial write.
    """
    validate_boxes(bboxes)
    lbl_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for b in bboxes:
        try:
            if b.get('type') == 'polygon':
                pts  = ' '.join(f"{p['x']:.6f} {p['y']:.6f}" for p in b['points'])
                vals = [float(x)
                        for pair in b['points']
                        for x in (pair['x'], pair['y'])]
                if all(math.isfinite(v) and 0.0 <= v <= 1.0 for v in vals):
                    lines.append(f"{int(b['class_id'])} {pts}\n")
            else:
                xc, yc, w, h = (b['x_center'], b['y_center'],
                                 b['width'], b['height'])
                if (math.isfinite(xc) and math.isfinite(yc) and
                        math.isfinite(w) and math.isfinite(h) and
                        0.0 <= xc <= 1.0 and 0.0 <= yc <= 1.0 and
                        w > 0 and h > 0):
                    lines.append(
                        f"{int(b['class_id'])} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}\n"
                    )
        except (KeyError, ValueError, TypeError):
            continue

    if not lines:
        # Empty annotation = delete the label file so the image shows as unannotated
        if lbl_path.exists():
            lbl_path.unlink()
        return

    # Atomic write: temp file → rename
    tmp = lbl_path.with_suffix(f'.{uuid.uuid4().hex[:8]}.tmp')
    try:
        tmp.write_text(''.join(lines), encoding='utf-8')
        os.replace(str(tmp), str(lbl_path))
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


# ── Class-index remapping ─────────────────────────────────────────────────────
# A YOLO .txt line starts with a class INDEX, not a name, so any operation that
# moves labels between two class lists must rewrite that first column. Skip it
# and "sack"(id 2) in one project silently becomes "carton_box"(id 2) in another.
#
# These two live here (not in app/api/uploads.py, where they started) because
# both dataset import AND project merge need them, and core must not be reached
# through the API layer. uploads.py re-exports them under its old private names.

def merge_classes_and_remap(ws_folder: str, project: str,
                            incoming_names: list) -> dict:
    """
    Merge `incoming_names` (ordered — position = the source's class index) into
    the project's class list WITHOUT reusing deleted IDs.

    Returns a remap dict:  {source_index (int) → project_id (int)}

    Example:
      Project classes:  [{id:0,name:sack},{id:1,name:person},{id:3,name:dog}]
      Incoming names:   ['person', 'handbag']   (indices 0, 1 in source)
      After merge:      project gets handbag at id=4 (max+1)
      Remap returned:   {0: 1, 1: 4}
        → source label "0 ..."  becomes project id 1  (person)
        → source label "1 ..."  becomes project id 4  (handbag)

    An empty name marks a hole in the source list (a deleted class id) and is
    skipped, so it contributes no remap entry.
    """
    from app.core.storage import (DEFAULT_PALETTE, load_project_meta,
                                  save_project_meta)

    if not incoming_names:
        return {}

    meta    = load_project_meta(ws_folder, project)
    classes = meta.get('classes', [])

    name_to_id = {c['name']: c['id'] for c in classes}
    next_id    = (max(c['id'] for c in classes) + 1) if classes else 0

    remap   = {}
    changed = False

    for src_idx, name in enumerate(incoming_names):
        name = (name or '').strip()
        if not name:
            continue
        if name in name_to_id:
            remap[src_idx] = name_to_id[name]
        else:
            color = DEFAULT_PALETTE[next_id % len(DEFAULT_PALETTE)]
            classes.append({'id': next_id, 'name': name, 'color': color})
            name_to_id[name] = next_id
            remap[src_idx]   = next_id
            next_id         += 1
            changed          = True

    if changed:
        meta['classes'] = classes
        save_project_meta(ws_folder, project, meta)

    return remap


def remap_label_file(path, remap: dict):
    """
    Rewrite a YOLO .txt file replacing source class indices with project IDs.
    Only rewrites if any index actually changes. Preserves coordinates exactly.
    Skips lines that don't parse as valid YOLO format.
    """
    if not path.exists() or not remap:
        return
    try:
        original = path.read_text(encoding='utf-8', errors='ignore')
    except OSError:
        return

    lines_out = []
    changed   = False
    for line in original.splitlines():
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

    if changed:
        path.write_text('\n'.join(lines_out) + ('\n' if lines_out else ''),
                        encoding='utf-8')
