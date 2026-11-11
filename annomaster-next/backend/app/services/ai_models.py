"""
YOLO model registry — scan, validate, cache. Ported from the original app's
app/core/ai_models.py (same behaviour, same guarantees).

  • models/ is re-scanned per call — a .pt dropped in while running appears on
    the next request. Never cached at boot.
  • Loaded YOLO instances are cached keyed by (path, mtime, size). The original
    reloaded on every request — ~8s per detection on a 5MB checkpoint. The mtime
    in the key means re-training under the same filename still reloads.
  • Invalid weights raise ModelError (→ HTTP 422 with a readable message), never
    a bare 500. resolve_path strips directory parts so a name can't escape
    models/.
"""
import threading
from pathlib import Path

from app.core.config import get_settings

_cache: dict = {}
_lock = threading.Lock()


class ModelError(Exception):
    """Raised with a user-facing message when a model can't be used."""


def models_dir() -> Path:
    d = Path(get_settings().models_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _candidate_files() -> list[Path]:
    seen, out = set(), []
    for f in sorted(models_dir().glob('*.pt')):
        if f.name not in seen:
            seen.add(f.name)
            out.append(f)
    return out


def resolve_path(model_name: str) -> Path:
    """Bare filename → real file. Directory components are stripped, so a name
    like `../../x` cannot escape models/."""
    safe = Path(str(model_name or '')).name
    if not safe:
        raise ModelError('No model specified.')
    if not safe.endswith('.pt'):
        raise ModelError(f'"{safe}" is not a .pt weights file.')
    for f in _candidate_files():
        if f.name == safe:
            return f
    raise ModelError(f'Model "{safe}" was not found in models/.')


def _cache_key(path: Path):
    st = path.stat()
    return (str(path.resolve()), st.st_mtime_ns, st.st_size)


def _class_names(model) -> list[str]:
    names = getattr(model, 'names', None)
    if isinstance(names, dict):
        return [str(names[k]) for k in sorted(names)]
    if isinstance(names, (list, tuple)):
        return [str(n) for n in names]
    return []


def load(model_name: str):
    """A ready YOLO instance, cached on first use. Raises ModelError on failure."""
    path = resolve_path(model_name)
    try:
        key = _cache_key(path)
    except OSError as e:
        raise ModelError(f'Cannot read "{path.name}": {e}') from e

    with _lock:
        hit = _cache.get(key)
    if hit is not None:
        return hit

    try:
        from ultralytics import YOLO
    except ImportError as e:
        raise ModelError('ultralytics is not installed on the server.') from e
    try:
        model = YOLO(str(path))
    except Exception as e:
        raise ModelError(f'"{path.name}" could not be loaded as a YOLO model: {e}') from e
    if not _class_names(model):
        raise ModelError(f'"{path.name}" exposes no class names — not a detection model.')

    with _lock:
        _cache[key] = model
    return model


def class_names(model_name: str) -> list[str]:
    return _class_names(load(model_name))


def list_models(with_classes: bool = False) -> list[dict]:
    out = []
    for f in _candidate_files():
        try:
            size_mb = round(f.stat().st_size / (1024 * 1024), 1)
        except OSError:
            continue
        entry = {'name': f.name, 'size_mb': size_mb}
        if with_classes:
            try:
                entry['classes'] = class_names(f.name)
                entry['valid'] = True
            except ModelError as e:
                entry.update(classes=[], valid=False, error=str(e))
        out.append(entry)
    return out


def describe(model_name: str) -> dict:
    """Validate + return class list. Used when the UI selection changes, so an
    unusable file is reported before detection runs."""
    path = resolve_path(model_name)
    names = class_names(model_name)   # raises ModelError if unusable
    return {'name': path.name,
            'size_mb': round(path.stat().st_size / (1024 * 1024), 1),
            'classes': names, 'class_count': len(names), 'valid': True}
