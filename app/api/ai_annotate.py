"""AI Smart Detect — YOLO inference API for the annotation tool.

Model discovery, validation, class-list introspection and instance caching
live in `app.core.ai_models`; this module is the HTTP surface over it.

Per-project Smart Detect settings (selected model, confidence threshold,
mode) are persisted in the project's `project.json` under `settings.ai`,
so switching projects restores that project's own configuration instead of
falling back to a global default.
"""
from pathlib import Path
from flask import Blueprint, request, jsonify, g

from app.utils.security import login_required, workspace_role_required
from app.core.paths import project_dir
from app.core.storage import load_project_meta, save_project_meta
from app.core import ai_models
from app.core.ai_models import ModelError, MODELS_DIR
from app.core import prompt_models
from app.core import box_examples
from app.core import devices
from app.models.workspace import Workspace

ai_annotate_bp = Blueprint('ai_annotate', __name__)

# Defaults applied when a project has never been configured.
DEFAULT_AI_SETTINGS = {
    'model': None,          # resolved to the first available model on read
    'conf':  0.45,          # sensible starting threshold
    'mode':  'review',      # 'review' | 'autosave' — review is the safe default
    'iou':   0.5,           # duplicate-match threshold
}
VALID_MODES = ('review', 'autosave')


def _resolve_image(wsf, project, rel_path):
    """
    Project-relative image path → (absolute Path, None) or (None, error response).

    The client sends a path relative to the project. Without this check
    `project_dir / rel_path` accepts "../.." and, on Windows, an absolute
    path ("D:/…") — which REPLACES the base — so a request could run a model
    over any image on the server's disk. Resolve, then require the result
    to stay inside the project and be an image file.
    """
    base = project_dir(wsf, project).resolve()
    rel = str(rel_path).replace('\\', '/')
    if Path(rel).is_absolute() or Path(rel).drive or rel.startswith('/'):
        return None, (jsonify({'error': 'path must be relative to the project'}), 400)
    try:
        p = (base / rel).resolve()
    except (OSError, ValueError):
        return None, (jsonify({'error': 'Invalid image path'}), 400)
    if not p.is_relative_to(base):
        return None, (jsonify({'error': 'path must stay inside the project'}), 400)
    if p.suffix.lower() not in prompt_models.IMAGE_EXTS:
        return None, (jsonify({'error': f'Not an image file: {rel_path}'}), 400)
    if not p.is_file():
        return None, (jsonify({'error': f'Image not found: {rel_path}'}), 404)
    return p, None


def _wsf(wid):
    return Workspace.query.get_or_404(int(wid)).folder_name


# ─── List available models ────────────────────────────────────────────────────

@ai_annotate_bp.route('/api/ai/models', methods=['GET'])
@login_required
def api_ai_models():
    """
    Available .pt models. Re-scanned from disk on every call, so a file
    added while the server is running shows up on the next refresh without
    a restart.

    `?classes=1` also loads each model to read its class list. That is slow
    on a cold cache, so the UI uses it sparingly.
    """
    want_classes = request.args.get('classes') in ('1', 'true', 'yes')
    try:
        models = ai_models.list_models(with_classes=want_classes)
    except Exception as e:
        return jsonify({'error': f'Could not read models directory: {e}'}), 500
    return jsonify({'models': models, 'models_dir': str(MODELS_DIR)})


@ai_annotate_bp.route('/api/ai/models/<path:model_name>/info', methods=['GET'])
@login_required
def api_ai_model_info(model_name):
    """
    Validate one model and return its class list.

    Called when the selection changes so an unusable file is reported
    immediately, rather than surfacing as a failed detection later.
    """
    try:
        return jsonify(ai_models.describe(model_name))
    except ModelError as e:
        # 422: the request is well-formed, the *file* is the problem.
        return jsonify({'error': str(e), 'valid': False}), 422
    except Exception as e:
        return jsonify({'error': f'Unexpected error: {e}', 'valid': False}), 500


# ─── Upload a model ───────────────────────────────────────────────────────────

@ai_annotate_bp.route('/api/ai/upload_model', methods=['POST'])
@login_required
def api_ai_upload_model():
    """Upload a .pt YOLO model to the shared models directory."""
    if 'model' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    f = request.files['model']
    if not f.filename or not f.filename.endswith('.pt'):
        return jsonify({'error': 'Only .pt files are allowed'}), 400

    safe_name = Path(f.filename).name          # strip any directory component
    dest = MODELS_DIR / safe_name
    f.save(dest)

    # Validate immediately — accepting a file that cannot load only defers
    # the failure to the user's first detection run.
    try:
        info = ai_models.describe(safe_name)
    except ModelError as e:
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        return jsonify({'error': str(e)}), 422

    return jsonify({'success': True, **info})


# ─── Per-project Smart Detect settings ────────────────────────────────────────

def _read_ai_settings(wsf, project) -> dict:
    meta = load_project_meta(wsf, project) or {}
    saved = (meta.get('settings') or {}).get('ai') or {}
    out = {**DEFAULT_AI_SETTINGS, **saved}

    # Fall back to the first available model when unset or when the saved
    # one has since been deleted from models/.
    available = [m['name'] for m in ai_models.list_models()]
    if out.get('model') not in available:
        out['model'] = available[0] if available else None
    return out


@ai_annotate_bp.route(
    '/api/workspaces/<int:workspace_id>/projects/<project>/ai/settings',
    methods=['GET', 'PUT'])
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def api_ai_settings(workspace_id, project):
    wsf = _wsf(workspace_id)

    if request.method == 'GET':
        return jsonify(_read_ai_settings(wsf, project))

    if g.member_role not in ('owner', 'editor'):
        return jsonify({'error': 'Viewers cannot change project settings'}), 403

    data = request.json or {}
    current = _read_ai_settings(wsf, project)

    if 'model' in data and data['model']:
        try:
            ai_models.resolve_path(data['model'])   # existence check only
            current['model'] = Path(str(data['model'])).name
        except ModelError as e:
            return jsonify({'error': str(e)}), 422

    if 'conf' in data:
        try:
            current['conf'] = max(0.01, min(0.99, float(data['conf'])))
        except (TypeError, ValueError):
            return jsonify({'error': 'conf must be a number between 0 and 1'}), 400

    if 'iou' in data:
        try:
            current['iou'] = max(0.05, min(0.95, float(data['iou'])))
        except (TypeError, ValueError):
            return jsonify({'error': 'iou must be a number between 0 and 1'}), 400

    if 'mode' in data:
        if data['mode'] not in VALID_MODES:
            return jsonify({'error': f'mode must be one of {VALID_MODES}'}), 400
        current['mode'] = data['mode']

    meta = load_project_meta(wsf, project) or {}
    meta.setdefault('settings', {})['ai'] = current
    save_project_meta(wsf, project, meta)
    return jsonify(current)


# ─── Run YOLO prediction ──────────────────────────────────────────────────────

@ai_annotate_bp.route(
    '/api/workspaces/<int:workspace_id>/projects/<project>/ai/predict',
    methods=['POST'])
@login_required
@workspace_role_required('owner', 'editor')
def api_ai_predict(workspace_id, project):
    """
    Run YOLO inference on a single project image.

    Body: {"path": "...", "model": "best.pt", "conf": 0.45}
    `model`/`conf` are optional — the project's saved settings are used
    when they are omitted.

    Detections below `conf` are dropped by ultralytics itself, so they never
    reach the client in either Smart Detect mode.
    """
    data     = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Request body must be a JSON object'}), 400
    rel_path = data.get('path', '')
    if not rel_path:
        return jsonify({'error': 'path is required'}), 400

    wsf      = _wsf(workspace_id)
    settings = _read_ai_settings(wsf, project)

    model_name = data.get('model') or settings.get('model')
    if not model_name:
        return jsonify({
            'error': 'No YOLO model available. Add a .pt file to the models/ '
                     'directory or upload one from Smart Detect.'
        }), 422

    try:
        conf = float(data.get('conf', settings.get('conf', 0.45)))
    except (TypeError, ValueError):
        conf = 0.45
    conf = max(0.01, min(0.99, conf))

    img_path, err = _resolve_image(wsf, project, rel_path)
    if err:
        return err

    # Cached instance — no per-request checkpoint deserialisation.
    try:
        model = ai_models.load(model_name)
    except ModelError as e:
        return jsonify({'error': str(e)}), 422

    # GPU when available, CPU otherwise, with automatic fallback (see
    # core/devices.py). The predictor binds the model to a device the first
    # time it runs, so a retry on a different device must start a fresh one.
    def _attempt(device, half):
        if getattr(model, '_am_device', None) != (device, half):
            model.predictor = None
            model._am_device = (device, half)
        try:
            return model.predict(str(img_path), conf=conf, verbose=False,
                                 device=device, half=half)
        except Exception:
            model.predictor = None
            model._am_device = None
            raise

    try:
        results = devices.run(f'detect:{model_name}', _attempt)
    except Exception as e:
        return jsonify({'error': f'Detection failed on this image: {e}'}), 500

    predictions = []
    if results:
        boxes = results[0].boxes
        names = results[0].names
        if boxes is not None:
            for i in range(len(boxes)):
                cls_id = int(boxes.cls[i].item())
                xywhn  = boxes.xywhn[i].tolist()
                predictions.append({
                    'class_name':  names.get(cls_id, str(cls_id)),
                    'yolo_cls_id': cls_id,
                    'conf':        round(float(boxes.conf[i].item()), 4),
                    'x_center':    round(xywhn[0], 6),
                    'y_center':    round(xywhn[1], 6),
                    'width':       round(xywhn[2], 6),
                    'height':      round(xywhn[3], 6),
                })

    return jsonify({
        'predictions': predictions,
        'model': model_name,
        'conf': conf,
    })


# ─── Auto-Save audit trail ────────────────────────────────────────────────────

@ai_annotate_bp.route(
    '/api/workspaces/<int:workspace_id>/projects/<project>/ai/autosave_log',
    methods=['POST'])
@login_required
@workspace_role_required('owner', 'editor')
def api_ai_autosave_log(workspace_id, project):
    """
    Record an Auto-Save detection run.

    Auto-Save writes confirmed ground truth with NO human in the loop, so
    without this there is no trace of which boxes a model produced versus
    which a person drew. That distinction is what later QA and
    model-performance review depend on.
    """
    d = request.json or {}
    try:
        from app.models.audit_log import log_action
        log_action(
            'ai.autosave',
            user_id=g.current_user.id,
            workspace_id=workspace_id,
            project=project,
            image_path=d.get('path', ''),
            detail={
                'model':    d.get('model'),
                'conf':     d.get('conf'),
                'iou':      d.get('iou'),
                'added':    int(d.get('added') or 0),
                'replaced': int(d.get('replaced') or 0),
                'total':    int(d.get('total') or 0),
            },
            ip=request.remote_addr,
        )
    except Exception:
        # Never fail the annotation flow because the audit write failed.
        pass
    return jsonify({'success': True})


# ═══════════════════════════════════════════════════════════════════════════════
# PROMPTED ANNOTATION — text prompting + box prompting
#
# Smart Detect (above) runs a fixed detector: the model decides what the
# classes are. This surface is the inverse — the USER supplies the class
# set per request, as words or as an example box, and an open-vocabulary
# model answers for that prompt alone.
#
# What it deliberately shares with Smart Detect: the prediction wire shape.
# The browser commits both through `Boxes.reconcile()`, so a prompt result
# is a SUGGESTION with the same review lifecycle, the same
# `.suggestions.json` sidecar and the same "only confirmed boxes are
# exported" guarantee. Nothing here writes ground truth.
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_PROMPT_SETTINGS = {
    'engine':  None,        # resolved to the default engine on read
    'conf':    0.4,         # DISPLAY threshold — applied in the browser
    'mode':    'text',      # 'text' | 'box'
    'phrases': [],          # last prompt, so it survives a reload
    'auto':    True,        # box tab: predict from the example library on each image
}


@ai_annotate_bp.route('/api/ai/prompt/engines', methods=['GET'])
@login_required
def api_ai_prompt_engines():
    """
    Which prompt engines exist, and what using one costs right now.

    `installed` and `download_mb` let the UI warn BEFORE a first run pulls
    hundreds of megabytes, instead of parking the user on a spinner. Like
    the Smart Detect model list, this is re-derived from disk per request —
    dropping a `sam3*.pt` into models/ enables that engine on refresh.
    """
    try:
        return jsonify({
            'engines': prompt_models.list_engines(),
            'default': prompt_models.DEFAULT_ENGINE,
            'conf_floor': prompt_models.CONF_FLOOR,
        })
    except Exception as e:
        return jsonify({'error': f'Could not list prompt engines: {e}'}), 500


def _read_prompt_settings(wsf, project) -> dict:
    meta = load_project_meta(wsf, project) or {}
    saved = (meta.get('settings') or {}).get('ai_prompt') or {}
    out = {**DEFAULT_PROMPT_SETTINGS, **saved}
    if out.get('engine') not in prompt_models.ENGINES:
        out['engine'] = prompt_models.DEFAULT_ENGINE
    return out


@ai_annotate_bp.route(
    '/api/workspaces/<int:workspace_id>/projects/<project>/ai/prompt/settings',
    methods=['GET', 'PUT'])
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def api_ai_prompt_settings(workspace_id, project):
    """
    Per-project prompt settings, stored in project.json under
    `settings.ai_prompt` — same reasoning as `settings.ai`: different
    projects look for different objects, so the prompt belongs to the
    project rather than to the browser.
    """
    wsf = _wsf(workspace_id)

    if request.method == 'GET':
        return jsonify(_read_prompt_settings(wsf, project))

    if g.member_role not in ('owner', 'editor'):
        return jsonify({'error': 'Viewers cannot change project settings'}), 403

    data = request.json or {}
    current = _read_prompt_settings(wsf, project)

    if 'engine' in data and data['engine']:
        if data['engine'] not in prompt_models.ENGINES:
            return jsonify({'error': f'Unknown engine "{data["engine"]}"'}), 400
        current['engine'] = data['engine']

    if 'conf' in data:
        try:
            current['conf'] = max(0.01, min(0.99, float(data['conf'])))
        except (TypeError, ValueError):
            return jsonify({'error': 'conf must be a number between 0 and 1'}), 400

    if 'mode' in data:
        if data['mode'] not in (prompt_models.TEXT, prompt_models.BOX):
            return jsonify({'error': 'mode must be "text" or "box"'}), 400
        current['mode'] = data['mode']

    if 'auto' in data:
        current['auto'] = bool(data['auto'])

    if 'phrases' in data:
        try:
            current['phrases'] = [str(p)[:64] for p in (data['phrases'] or [])
                                  ][:prompt_models.MAX_PHRASES]
        except TypeError:
            return jsonify({'error': 'phrases must be a list'}), 400

    meta = load_project_meta(wsf, project) or {}
    meta.setdefault('settings', {})['ai_prompt'] = current
    save_project_meta(wsf, project, meta)
    return jsonify(current)


@ai_annotate_bp.route(
    '/api/workspaces/<int:workspace_id>/projects/<project>/ai/prompt',
    methods=['POST'])
@login_required
@workspace_role_required('owner', 'editor')
def api_ai_prompt(workspace_id, project):
    """
    Run one prompted pass over a single project image.

    Body:
      {"path": "...", "mode": "text", "phrases": ["person", "helmet"]}
      {"path": "...", "mode": "box",  "boxes": [{"x1":..,"y1":..,"x2":..,
                                                 "y2":..,"label":"crate"}]}

    `conf` is a FLOOR, not the user's threshold. The response carries every
    detection above it and the browser filters live as the slider moves —
    re-running inference on each slider tick would cost seconds per step.
    """
    import time

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Request body must be a JSON object'}), 400
    rel_path = data.get('path', '')
    if not rel_path:
        return jsonify({'error': 'path is required'}), 400

    wsf = _wsf(workspace_id)
    settings = _read_prompt_settings(wsf, project)
    engine = data.get('engine') or settings.get('engine')
    mode = data.get('mode') or settings.get('mode') or prompt_models.TEXT
    if mode not in (prompt_models.TEXT, prompt_models.BOX, 'examples'):
        return jsonify({'error': 'mode must be "text", "box" or "examples"'}), 400

    img_path, err = _resolve_image(wsf, project, rel_path)
    if err:
        return err

    nums = {}
    for key, default in (('conf', prompt_models.CONF_FLOOR), ('iou', 0.5)):
        raw = data.get(key)
        try:
            nums[key] = default if raw is None else float(raw)
        except (TypeError, ValueError):
            return jsonify({'error': f'{key} must be a number between 0 and 1'}), 400
    conf, iou = nums['conf'], nums['iou']

    started = time.time()
    try:
        if mode == 'examples':
            # Roboflow-style: predict from the project's saved example library
            # (core/box_examples.py), whatever image those examples were drawn on.
            meta = load_project_meta(wsf, project) or {}
            class_names = {int(c['id']): c['name'] for c in meta.get('classes', [])}
            out = prompt_models.predict_examples(
                img_path, box_examples.load(wsf, project), project_dir(wsf, project),
                class_names, engine=engine, conf=conf, iou=iou)
        else:
            out = prompt_models.predict(
                img_path,
                engine=engine,
                mode=mode,
                phrases=data.get('phrases'),
                boxes=data.get('boxes'),
                conf=conf,
                iou=iou,
            )
    except ModelError as e:
        # 422: the request is fine, the model or the prompt is the problem.
        return jsonify({'error': str(e)}), 422
    except Exception as e:
        return jsonify({'error': f'Prompt failed on this image: {e}'}), 500

    out['elapsed_ms'] = int((time.time() - started) * 1000)
    out['conf_floor'] = conf

    # Suggestions still need a trail of which engine and which prompt
    # produced them — that is what later QA reads to tell a model's output
    # from a person's. Best-effort: never fail the run on an audit write.
    try:
        from app.models.audit_log import log_action
        log_action(
            'ai.prompt',
            user_id=g.current_user.id,
            workspace_id=workspace_id,
            project=project,
            image_path=rel_path,
            detail={
                'engine':  out.get('engine'),
                'mode':    mode,
                'labels':  out.get('labels'),
                'count':   len(out.get('predictions') or []),
                'elapsed_ms': out['elapsed_ms'],
            },
            ip=request.remote_addr,
        )
    except Exception:
        pass

    return jsonify(out)


# ── Box-prompt example library (Roboflow-style "teach by example") ─────────────

@ai_annotate_bp.route(
    '/api/workspaces/<int:workspace_id>/projects/<project>/ai/examples',
    methods=['GET', 'POST', 'DELETE'])
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def api_ai_examples(workspace_id, project):
    """
    The project's saved box-prompt examples (core/box_examples.py).

    GET    → {"examples": [...], "counts": {class_id: {"positive": n, "negative": n}}}
    POST   {"image": "<rel path>", "boxes": [{"x1","y1","x2","y2" (0-1),
                                              "class_id", "positive"}]}
    DELETE {"ids": [...]} | {"image": "..."} | {"class_id": n} | {"all": true}

    Examples are prompts, never annotations: they don't touch any label file.
    """
    wsf = _wsf(workspace_id)

    def listing():
        rows = box_examples.load(wsf, project)
        counts = {}
        for r in rows:
            c = counts.setdefault(str(r['class_id']), {'positive': 0, 'negative': 0})
            c['positive' if r.get('positive', True) else 'negative'] += 1
        return {'examples': rows, 'counts': counts, 'max': box_examples.MAX_EXAMPLES}

    if request.method == 'GET':
        return jsonify(listing())

    if g.member_role not in ('owner', 'editor'):
        return jsonify({'error': 'Viewers cannot change the example library'}), 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Request body must be a JSON object'}), 400

    try:
        if request.method == 'POST':
            img_path, err = _resolve_image(wsf, project, data.get('image', ''))
            if err:
                return err
            meta = load_project_meta(wsf, project) or {}
            valid = {int(c['id']) for c in meta.get('classes', [])}
            added = box_examples.add(wsf, project, data.get('image'), data.get('boxes'),
                                     user_id=g.current_user.id, valid_class_ids=valid)
            return jsonify({**listing(), 'added': added})

        cid = data.get('class_id')
        n = box_examples.remove(
            wsf, project, ids=data.get('ids'), image=data.get('image'),
            class_id=int(cid) if cid is not None else None,
            everything=bool(data.get('all')))
        return jsonify({**listing(), 'removed': n})
    except box_examples.ExampleError as e:
        return jsonify({'error': str(e)}), 422
    except (TypeError, ValueError) as e:
        return jsonify({'error': f'Bad request: {e}'}), 400
