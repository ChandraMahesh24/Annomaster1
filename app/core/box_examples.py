"""
Box-prompt example library — Roboflow-style "teach by example".

WHAT IT IS
──────────
The user draws a few boxes and says "this is a 1_staff" / "this is NOT".
Those boxes are kept per project and used as prompts on every later image,
so the model predicts that class without a word describing it. The more
examples, the better it separates look-alike classes (measured on project
`m`: staff-vs-customer accuracy on the true boxes 0.76 with 3 example frames
→ 0.86 with 6). The inference side is `prompt_models.predict_examples`.

WHAT IT IS NOT
──────────────
An annotation. Examples live in `prompt_examples.json` beside project.json —
never in a label file or the suggestions sidecar — so they cannot reach an
export, a dataset build or `Image.is_annotated`. Same rule as the per-image
exemplars (`state.promptBoxes`) they replace.

FORMAT
──────
    {"version": 1, "examples": [
        {"id": "ex_3f9a1c2b", "class_id": 3, "positive": true,
         "image": "Active_Work/job_…/images/frame.jpg",      # project-relative, '/'
         "box": [x1, y1, x2, y2],                            # normalised 0-1
         "created_by": 1, "created_at": "2026-11-12T10:00:00"}]}

`image` + `box` is all inference needs: the box is re-encoded on its own
image (cached in memory), so the library stays valid across model upgrades.
"""
import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

from app.core.paths import prompt_examples_file

SCHEMA_VERSION = 1

# Every example costs one backbone pass on its image the first time it is
# used after a restart (~0.5 s on the RTX 3050, ~20 s on CPU), and adds
# prompt tokens to every prediction. Generous for "a few examples per class".
MAX_EXAMPLES = 200
MIN_BOX = 0.002          # normalised side; anything smaller is a stray click

_lock = threading.Lock()


class ExampleError(ValueError):
    """A request the user can fix (bad box, too many examples) — HTTP 400/422."""


def norm_image_path(rel) -> str:
    return str(rel or '').replace('\\', '/').lstrip('/')


def _read(path: Path) -> list:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    rows = data.get('examples') if isinstance(data, dict) else None
    return [r for r in (rows or []) if isinstance(r, dict) and 'box' in r and 'image' in r]


def _write(path: Path, rows: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f'.{uuid.uuid4().hex[:8]}.tmp')
    try:
        tmp.write_text(json.dumps({'version': SCHEMA_VERSION, 'examples': rows},
                                  ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(str(tmp), str(path))
    finally:
        tmp.unlink(missing_ok=True)


def load(ws_folder: str, project: str) -> list:
    return _read(prompt_examples_file(ws_folder, project))


def _clean_box(b) -> list:
    try:
        x1, y1, x2, y2 = (float(b[k]) for k in ('x1', 'y1', 'x2', 'y2'))
    except (KeyError, TypeError, ValueError):
        raise ExampleError('Each example needs numeric x1, y1, x2, y2 (normalised 0-1).')
    x1, x2 = sorted((min(max(x1, 0.0), 1.0), min(max(x2, 0.0), 1.0)))
    y1, y2 = sorted((min(max(y1, 0.0), 1.0), min(max(y2, 0.0), 1.0)))
    if x2 - x1 < MIN_BOX or y2 - y1 < MIN_BOX:
        raise ExampleError('Example box is too small — drag a box around the whole object.')
    return [round(x1, 6), round(y1, 6), round(x2, 6), round(y2, 6)]


def add(ws_folder: str, project: str, image: str, boxes: list, user_id=None,
        valid_class_ids=None) -> list:
    """Append examples drawn on `image`; returns the stored rows."""
    image = norm_image_path(image)
    if not image:
        raise ExampleError('image is required')
    if not isinstance(boxes, list) or not boxes:
        raise ExampleError('Send at least one example box.')
    new = []
    for b in boxes:
        if not isinstance(b, dict):
            raise ExampleError('Each example must be an object.')
        try:
            cid = int(b.get('class_id'))
        except (TypeError, ValueError):
            raise ExampleError('Each example needs the class it shows (class_id).')
        if valid_class_ids is not None and cid not in valid_class_ids:
            raise ExampleError(f'Class id {cid} does not exist in this project.')
        new.append({
            'id': 'ex_' + uuid.uuid4().hex[:8],
            'class_id': cid,
            'positive': bool(b.get('positive', True)),
            'image': image,
            'box': _clean_box(b),
            'created_by': user_id,
            'created_at': datetime.utcnow().isoformat(timespec='seconds'),
        })
    path = prompt_examples_file(ws_folder, project)
    with _lock:
        rows = _read(path)
        if len(rows) + len(new) > MAX_EXAMPLES:
            raise ExampleError(f'The example library is full ({MAX_EXAMPLES}). '
                               'Remove some examples first.')
        # Same box drawn twice on the same image (double-click, re-run of
        # "use my boxes") is one example, not two.
        seen = {(r['image'], r['class_id'], r['positive'], tuple(r['box'])) for r in rows}
        new = [n for n in new if (n['image'], n['class_id'], n['positive'], tuple(n['box'])) not in seen]
        if new:
            _write(path, rows + new)
    return new


def remove(ws_folder: str, project: str, ids=None, image=None, class_id=None,
           everything=False) -> int:
    """Delete by id list, by image, by class, or all. Returns the count removed."""
    path = prompt_examples_file(ws_folder, project)
    want_ids = set(ids or [])
    image = norm_image_path(image) if image else None
    if not (want_ids or image or class_id is not None or everything):
        raise ExampleError('Say which examples to remove (ids, image, class_id or all).')
    with _lock:
        rows = _read(path)

        def doomed(r):
            if everything:
                return True
            if want_ids and r.get('id') in want_ids:
                return True
            if image and r.get('image') == image and (class_id is None or r.get('class_id') == class_id):
                return True
            if class_id is not None and not image and not want_ids and r.get('class_id') == class_id:
                return True
            return False

        keep = [r for r in rows if not doomed(r)]
        n = len(rows) - len(keep)
        if n:
            _write(path, keep)
    return n
