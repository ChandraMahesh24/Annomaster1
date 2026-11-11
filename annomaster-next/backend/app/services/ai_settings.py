"""
Per-project Smart Detect settings, stored in project.json under `settings.ai`.

Per-project (not global/localStorage) because different projects target
different object sets, so each keeps its own model + thresholds. `review` is the
default mode: Auto-Save writes ground truth with no human, so it must be opted
into, never the fallback.
"""
from app.services import ai_models, storage

DEFAULT_AI_SETTINGS = {'model': None, 'conf': 0.45, 'mode': 'review', 'iou': 0.5}
VALID_MODES = ('review', 'autosave')


def read_ai_settings(folder: str, project: str) -> dict:
    meta = storage.load_project_meta(folder, project) or {}
    saved = (meta.get('settings') or {}).get('ai') or {}
    out = {**DEFAULT_AI_SETTINGS, **saved}
    # Fall back to the first available model when unset or the saved one is gone.
    available = [m['name'] for m in ai_models.list_models()]
    if out.get('model') not in available:
        out['model'] = available[0] if available else None
    return out


def write_ai_settings(folder: str, project: str, patch: dict) -> dict:
    current = read_ai_settings(folder, project)
    if patch.get('model'):
        ai_models.resolve_path(patch['model'])          # existence check (raises ModelError)
        from pathlib import Path
        current['model'] = Path(str(patch['model'])).name
    if 'conf' in patch:
        current['conf'] = max(0.01, min(0.99, float(patch['conf'])))
    if 'iou' in patch:
        current['iou'] = max(0.05, min(0.95, float(patch['iou'])))
    if 'mode' in patch:
        if patch['mode'] not in VALID_MODES:
            raise ValueError(f'mode must be one of {VALID_MODES}')
        current['mode'] = patch['mode']

    meta = storage.load_project_meta(folder, project) or {}
    meta.setdefault('settings', {})['ai'] = current
    storage.save_project_meta(folder, project, meta)
    return current
