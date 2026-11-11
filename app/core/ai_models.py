"""
YOLO model registry for Smart Detect.

RESPONSIBILITIES
────────────────
  • Discover `.pt` weight files in models/ on every call (never cached at
    boot, so dropping a new file in while the server runs makes it appear
    on the next refresh).
  • Validate that a file actually loads as a YOLO model before detection
    runs, so a corrupt or non-YOLO `.pt` produces a clear message instead
    of a raw 500 and a spinner stuck on "detecting…".
  • Expose each model's own class list, read from the weights' metadata.
    This matters because a `.pt` may have been trained on a completely
    different class set than the project's own class list.
  • Cache loaded YOLO instances.

WHY THE INSTANCE CACHE EXISTS
─────────────────────────────
`api_ai_predict` previously ran `YOLO(model_str)` on every single request.
Constructing a YOLO object deserialises the whole checkpoint — for the
5 MB weights in this repo that is roughly a second of CPU per detection,
paid again for every frame, and far more for larger weights. Since the
files are immutable while loaded, the instance is cached and keyed by
(resolved path, mtime, size). Touching or replacing the file changes the
key, so a re-trained model with the same filename is picked up without a
restart rather than silently serving the stale weights.

THREAD SAFETY
─────────────
Flask's dev server is threaded, so the cache is guarded by a lock. The
lock is held only around dictionary access, never across the (slow) model
load — two concurrent first-loads of the same model would both construct
it and the last writer wins, which is harmless.
"""
import threading
from pathlib import Path

# Shared across all workspaces — a model is a global asset, not project data.
MODELS_DIR = Path(__file__).parent.parent.parent / 'models'
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# Bundled defaults that live at the repo root rather than in models/.
_EXTRA_SEARCH_DIRS = [Path(__file__).parent.parent.parent]

# Every directory a weights file may live in, in priority order. Public
# because the promptable-model registry (core/prompt_models.py) has to look
# in exactly the same places: a checkpoint dropped next to run.py is found
# by Smart Detect, and it would be baffling for the prompt engines to then
# report that same file as missing.
SEARCH_DIRS = [MODELS_DIR, *_EXTRA_SEARCH_DIRS]

_cache = {}
_cache_lock = threading.Lock()


class ModelError(Exception):
    """Raised with a message intended to be shown to the user."""


# ── Discovery ─────────────────────────────────────────────────────────────────

# Weights that belong to the PROMPTABLE engines (core/prompt_models.py),
# not to Smart Detect. These answer a prompt, not a fixed class list: run
# without one they either fail to load (SAM) or reply from a vocabulary
# nobody chose (YOLOE / YOLO-World), so listing them in the Smart Detect
# picker is a trap — the user gets a 422 or a nonsense detection.
# The patterns live here rather than being imported from prompt_models,
# because that module imports this one.
_PROMPT_ONLY_GLOBS = (
    'yoloe-*', 'sam3*', 'sam2*', 'sam_*', 'mobile_sam*', 'FastSAM*', '*-world*',
)


def _is_prompt_only(name: str) -> bool:
    from fnmatch import fnmatch
    return any(fnmatch(name, pat) for pat in _PROMPT_ONLY_GLOBS)


def _candidate_files():
    """Every .pt we are willing to serve, de-duplicated by filename."""
    seen, out = set(), []
    for d in SEARCH_DIRS:
        if not d.exists():
            continue
        for f in sorted(d.glob('*.pt')):
            if f.name in seen or _is_prompt_only(f.name):
                continue
            seen.add(f.name)
            out.append(f)
    return out


def resolve_path(model_name: str) -> Path:
    """
    Map a bare filename to a real file on disk.

    Only the *name* is honoured — any directory component is stripped, so a
    request for `../../etc/passwd` or an absolute path cannot escape the
    model directories.
    """
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
    # mtime+size in the key means replacing the file invalidates the entry,
    # so a re-trained model with the same name is reloaded automatically.
    return (str(path.resolve()), st.st_mtime_ns, st.st_size)


# ── Loading ───────────────────────────────────────────────────────────────────

def load(model_name: str):
    """
    Return a ready YOLO instance, loading and caching on first use.

    Raises ModelError with a user-facing message on any failure.
    """
    path = resolve_path(model_name)
    try:
        key = _cache_key(path)
    except OSError as e:
        raise ModelError(f'Cannot read "{path.name}": {e}') from e

    with _cache_lock:
        hit = _cache.get(key)
    if hit is not None:
        return hit

    try:
        from ultralytics import YOLO
    except ImportError as e:
        raise ModelError(
            'ultralytics is not installed on the server. '
            'Run: pip install ultralytics'
        ) from e

    try:
        model = YOLO(str(path))
    except Exception as e:
        # Corrupt checkpoint, a non-YOLO .pt, a torch version mismatch…
        # Surface the real reason rather than a generic 500.
        raise ModelError(
            f'"{path.name}" could not be loaded as a YOLO model: {e}'
        ) from e

    if not _class_names(model):
        raise ModelError(
            f'"{path.name}" loaded but exposes no class names — '
            'it does not look like a YOLO detection model.'
        )

    with _cache_lock:
        _cache[key] = model
    return model


def _class_names(model) -> list:
    """Class list from the weights' metadata, ordered by class id."""
    names = getattr(model, 'names', None)
    if isinstance(names, dict):
        return [str(names[k]) for k in sorted(names)]
    if isinstance(names, (list, tuple)):
        return [str(n) for n in names]
    return []


def class_names(model_name: str) -> list:
    return _class_names(load(model_name))


# ── Listing ───────────────────────────────────────────────────────────────────

def list_models(with_classes: bool = False) -> list:
    """
    Every available model, re-scanned from disk on each call.

    `with_classes=True` loads each model to read its class list, which is
    slow on a cold cache — the API only does this for a single named model,
    not for the whole list.
    """
    out = []
    for f in _candidate_files():
        try:
            size_mb = round(f.stat().st_size / (1024 * 1024), 1)
        except OSError:
            continue
        entry = {'name': f.name, 'size_mb': size_mb, 'location': f.parent.name or '.'}
        if with_classes:
            try:
                entry['classes'] = class_names(f.name)
                entry['valid'] = True
            except ModelError as e:
                entry['classes'] = []
                entry['valid'] = False
                entry['error'] = str(e)
        out.append(entry)
    return out


def describe(model_name: str) -> dict:
    """
    Validate a model and report its class list.

    Used by the UI when the selection changes, so the user can see what a
    model can detect *before* running it — and gets an immediate error if
    the file is unusable, rather than at detection time.
    """
    path = resolve_path(model_name)
    names = class_names(model_name)   # raises ModelError when unusable
    return {
        'name':        path.name,
        'size_mb':     round(path.stat().st_size / (1024 * 1024), 1),
        'classes':     names,
        'class_count': len(names),
        'valid':       True,
    }
