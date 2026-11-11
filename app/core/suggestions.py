"""
Model-assisted labeling — suggestion sidecar store.

WHY A SIDECAR AND NOT THE LABEL FILE
────────────────────────────────────
The persisted annotation format is YOLO `.txt`:

    <class_id> <x_center> <y_center> <width> <height>

There is no field available for a review state or a confidence score, and
that format is deliberately fixed — it is what every downstream consumer
(export, dataset build, version snapshot, training) reads.

So the split is:

    labels/<name>.txt                 CONFIRMED boxes only — ground truth
    labels/<name>.suggestions.json    suggested + rejected boxes + confidence

This gives three properties for free, with no change to any exporter:

  1. Exports contain only human-confirmed ground truth. `core/versions.py`
     and `core/datasets.py` copy labels by explicit `<stem>.txt` name (they
     never glob the labels directory), so the sidecar can never leak into
     an exported dataset and poison training data.
  2. `is_valid_annotation_file()` — and therefore `Image.is_annotated` —
     only flips true once a real confirmed box exists. Running Smart Detect
     on a frame does not mark it annotated.
  3. Rejected boxes survive a page reload, so re-running detection can
     honour "the user already said no to this" instead of relying on a
     session flag that resets.

SIDECAR SHAPE
─────────────
    {
      "version": 1,
      "boxes": [
        {"id": "...", "state": "suggested"|"rejected", "class_id": 3,
         "type": "bbox", "x_center": .5, "y_center": .5,
         "width": .2, "height": .3, "confidence": 0.87}
      ]
    }

Coordinates are normalised 0..1, matching the YOLO convention, so a box can
move between the sidecar and the label file without a conversion step.
"""
import json
import os
import uuid
from pathlib import Path

SIDECAR_SUFFIX = '.suggestions.json'
SCHEMA_VERSION = 1

VALID_STATES = ('suggested', 'rejected')


def sidecar_path_for_label(lbl_path: Path) -> Path:
    """labels/foo.txt → labels/foo.suggestions.json"""
    return lbl_path.with_suffix('').with_name(lbl_path.stem + SIDECAR_SUFFIX)


def read_suggestions(lbl_path: Path) -> list:
    """
    Return the sidecar's boxes, or [] when absent/unreadable.

    Never raises: a corrupt sidecar must not block annotation work, since
    the label file is the real source of truth.
    """
    sc = sidecar_path_for_label(lbl_path)
    if not sc.exists():
        return []
    try:
        data = json.loads(sc.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    out = []
    for b in data.get('boxes', []):
        if not isinstance(b, dict):
            continue
        if b.get('state') not in VALID_STATES:
            continue
        try:
            box = {
                'id':         str(b.get('id') or uuid.uuid4().hex[:12]),
                'state':      b['state'],
                'class_id':   int(b.get('class_id', 0)),
                'type':       b.get('type', 'bbox'),
                'confidence': _opt_float(b.get('confidence')),
            }
            if box['type'] == 'polygon':
                pts = [{'x': float(p['x']), 'y': float(p['y'])}
                       for p in b.get('points', [])]
                if len(pts) < 3 or not _all_unit(v for p in pts for v in (p['x'], p['y'])):
                    continue
                box['points'] = pts
            else:
                for k in ('x_center', 'y_center', 'width', 'height'):
                    box[k] = float(b[k])
                if not _all_unit([box['x_center'], box['y_center']]):
                    continue
                if box['width'] <= 0 or box['height'] <= 0:
                    continue
            out.append(box)
        except (KeyError, TypeError, ValueError):
            continue
    return out


def write_suggestions(lbl_path: Path, boxes: list):
    """
    Write the sidecar atomically (temp + os.replace), mirroring
    write_yolo_label so a reader never sees a partial file.

    An empty list deletes the sidecar rather than leaving `{"boxes": []}`
    behind, keeping the labels directory clean.
    """
    sc = sidecar_path_for_label(lbl_path)
    keep = [b for b in (boxes or []) if b.get('state') in VALID_STATES]

    if not keep:
        try:
            sc.unlink(missing_ok=True)
        except OSError:
            pass
        return

    sc.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {'version': SCHEMA_VERSION, 'boxes': keep},
        separators=(',', ':'),
    )
    tmp = sc.with_suffix(f'.{uuid.uuid4().hex[:8]}.tmp')
    try:
        tmp.write_text(payload, encoding='utf-8')
        os.replace(str(tmp), str(sc))
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def delete_suggestions(lbl_path: Path):
    try:
        sidecar_path_for_label(lbl_path).unlink(missing_ok=True)
    except OSError:
        pass


# ── helpers ───────────────────────────────────────────────────────────────────

def _opt_float(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _all_unit(vals) -> bool:
    return all(isinstance(v, float) and 0.0 <= v <= 1.0 and v == v for v in vals)
