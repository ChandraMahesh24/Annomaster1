"""
Suggestion sidecar store.

    labels/<name>.txt                 CONFIRMED boxes  → ground truth, exports
    labels/<name>.suggestions.json    suggested + rejected boxes + confidence

Kept OUT of the .txt on purpose: a model prediction is a suggestion, never an
annotation, until a human confirms it. `rejected` boxes are retained (not
rendered) so a re-run of Smart Detect won't re-suggest what the user already
turned down. The label copiers in B4 copy by explicit `<stem>.txt`, never by
globbing, so this sidecar can't leak into a dataset.
"""
import json
import os
import uuid
from pathlib import Path

SIDECAR_SUFFIX = '.suggestions.json'


def _sidecar(lbl_path: Path) -> Path:
    """labels/foo.txt → labels/foo.suggestions.json"""
    return lbl_path.parent / (lbl_path.stem + SIDECAR_SUFFIX)


def read_suggestions(lbl_path: Path) -> list[dict]:
    """Sidecar boxes, or [] when absent/unreadable. Never raises."""
    p = _sidecar(lbl_path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
        return data if isinstance(data, list) else data.get('boxes', [])
    except Exception:
        return []


def write_suggestions(lbl_path: Path, boxes: list[dict]) -> None:
    """Write the sidecar atomically; an empty list DELETES it (nothing pending)."""
    p = _sidecar(lbl_path)
    if not boxes:
        p.unlink(missing_ok=True)
        return
    from app.core.fsutil import atomic_write
    atomic_write(p, json.dumps(boxes, ensure_ascii=False))


def delete_suggestions(lbl_path: Path) -> None:
    _sidecar(lbl_path).unlink(missing_ok=True)
