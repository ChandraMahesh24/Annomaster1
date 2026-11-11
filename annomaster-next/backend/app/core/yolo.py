"""
YOLO label file read/write.

The `.txt` holds CONFIRMED boxes only — this is the single guarantee that
unreviewed model predictions never reach an export, a dataset build, or a
training run (all of which read the .txt). Suggested/rejected boxes live in the
`.suggestions.json` sidecar instead.

Line formats (both ported):
  bbox     :  <cls> <xc> <yc> <w> <h>            (5 normalised floats)
  polygon  :  <cls> <x1> <y1> <x2> <y2> …        (cls + >=3 point pairs)
"""
from pathlib import Path


def parse_yolo_label(path: Path) -> list[dict]:
    """Read a .txt into a list of box dicts. Empty/missing → []."""
    if not path.exists():
        return []
    boxes: list[dict] = []
    for line in path.read_text(encoding='utf-8', errors='ignore').splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        try:
            cls = int(float(parts[0]))
            coords = [float(x) for x in parts[1:]]
        except ValueError:
            continue
        if len(coords) == 4:
            boxes.append({'class_id': cls, 'type': 'bbox',
                          'x_center': coords[0], 'y_center': coords[1],
                          'width': coords[2], 'height': coords[3]})
        elif len(coords) >= 6 and len(coords) % 2 == 0:
            pts = [{'x': coords[i], 'y': coords[i + 1]}
                   for i in range(0, len(coords), 2)]
            boxes.append({'class_id': cls, 'type': 'polygon', 'points': pts})
        # anything else → skip (malformed)
    return boxes


def _fmt(n: float) -> str:
    return f'{n:.6f}'.rstrip('0').rstrip('.')


def write_yolo_label(path: Path, boxes: list[dict]) -> None:
    """
    Write boxes to a .txt (atomic). An empty list writes an EMPTY file, not a
    missing one — a YOLO 'background' image needs the empty .txt to exist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for b in boxes:
        cls = b.get('class_id', b.get('cls'))
        if cls is None:
            continue
        if b.get('type') == 'polygon':
            pts = b.get('points') or []
            if len(pts) < 3:
                continue
            flat = ' '.join(f'{_fmt(p["x"])} {_fmt(p["y"])}' for p in pts)
            lines.append(f'{int(cls)} {flat}')
        else:
            try:
                xc, yc = float(b['x_center']), float(b['y_center'])
                w, h = float(b['width']), float(b['height'])
            except (KeyError, TypeError, ValueError):
                continue
            if w <= 0 or h <= 0:
                continue
            lines.append(f'{int(cls)} {_fmt(xc)} {_fmt(yc)} {_fmt(w)} {_fmt(h)}')

    from app.core.fsutil import atomic_write
    atomic_write(path, ('\n'.join(lines) + '\n') if lines else '')


def is_valid_annotation_file(path: Path) -> bool:
    """True only if the .txt exists and contains at least one valid box line."""
    return len(parse_yolo_label(path)) > 0
