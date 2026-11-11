"""
Promptable annotation engine — TEXT prompting and BOX prompting via SAM3.

WHY THIS IS NOT PART OF ai_models.py
────────────────────────────────────
`ai_models` serves exactly one shape of model: a closed-vocabulary YOLO
detector whose class list was frozen at training time. Everything in it
assumes that — discovery by `.pt` glob, "which classes can this file
detect", validation by reading `model.names`. That module stays the home
of **Smart Detect**, which runs the project's own trained weights.

A promptable model inverts that assumption. Its class set is supplied per
REQUEST, either as words ("person, helmet") or as an example box drawn on
the image, and the same weights answer a different question on every call.
Bolting that onto `ai_models.describe()` would have made "the classes this
model detects" meaningless for half its callers, so the two registries stay
separate. They deliberately share `MODELS_DIR`, `SEARCH_DIRS` and
`ModelError` — a model file is a model file, and both surfaces map a bad
one to HTTP 422.

THE ENGINE
──────────
**SAM3 only.** Earlier revisions also offered YOLOE and YOLO-World as
faster, auto-downloadable alternatives; they were removed on request, so
AI Annotate is SAM3 and Smart Detect is the user's own YOLO. The registry
shape is kept (one entry) because the panel still needs `modes`, `speed`
and availability reported the same way — and because that is what makes
adding an engine back a data change rather than a rewrite.

Consequences of SAM3 being the only engine, all of which the UI must say
out loud rather than discover at runtime:

  • The checkpoint is NOT published as an ultralytics asset, so it cannot
    be auto-downloaded. The engine reports itself unavailable until a
    `sam3*.pt` turns up in one of `ai_models.SEARCH_DIRS` (models/, or
    beside run.py). No download progress bar can help here.
  • Its text encoder lives INSIDE the checkpoint, so unlike the removed
    engines there is no second multi-hundred-MB download — but see
    `_ensure_clip_tokenizer_callable`.
  • It costs MINUTES per image without a GPU (~3 min measured on this
    machine's CPU-only torch, against ~1.6 s for the YOLOE it replaced).
    It is also markedly more accurate: 0.96 vs 0.77 on the same exemplar.

OUTPUT CONTRACT
───────────────
`predict()` returns the SAME normalised prediction dicts as
`api_ai_predict` — class_name / conf / x_center / y_center / width /
height, all box coordinates normalised 0-1. That is deliberate: the
browser then commits prompt output through the existing
`Boxes.reconcile()` path, so a prompt result is a SUGGESTION with the same
lifecycle, the same `.suggestions.json` sidecar and the same
confirmed-only export guarantee as a Smart Detect result. This feature
adds no second annotation lifecycle anywhere.

WHY predict() TAKES A CONFIDENCE FLOOR, NOT THE UI'S THRESHOLD
──────────────────────────────────────────────────────────────
Smart Detect passes the user's threshold to the model, so raising it means
re-running inference. Prompting is interactive — the user drags the slider
to watch the prediction count change — and with SAM3 a re-run costs
minutes. So the server runs once at a low floor and returns everything
above it; the client filters the cached list. Callers should pass
`CONF_FLOOR` and filter in the UI.

INSTANCE CACHING
────────────────
Same rule as `ai_models.load()`: cache keyed by (engine, path, mtime,
size), lock held only around dict access. This matters far more here than
for Smart Detect — SAM3 is a 3.45 GB checkpoint whose ViT backbone takes
tens of seconds to build, and that would otherwise be paid on every single
prompt.
"""
import threading
from pathlib import Path

from app.core.ai_models import SEARCH_DIRS, ModelError

TEXT = 'text'
BOX = 'box'

# The server always runs at this floor; the UI slider filters above it.
CONF_FLOOR = 0.05

# Guard rails on prompt size — every extra phrase is a pass through the
# text head, and every extra exemplar another visual embedding. With SAM3
# on CPU these are not theoretical: each one adds real seconds.
MAX_PHRASES = 20
MAX_EXEMPLARS = 10

DEFAULT_ENGINE = 'sam3'

ENGINES = {
    'sam3': {
        'label':        'SAM3',
        'modes':        (TEXT, BOX),
        # User-supplied: not an ultralytics release asset, so there is no
        # URL to fall back on. Discovered across SEARCH_DIRS.
        'weights_glob': 'sam3*.pt',
        'download_mb':  None,
        # Measured on this repo's CPU-only torch, 1920x1080 frame: ~3 min
        # per run. The UI has to say so before someone clicks Run and
        # assumes the app has hung.
        'speed':        'slow',
        'blurb':        'Concept segmentation — text and box prompts. Minutes per image on CPU.',
        # SAM3's backbone wants a multiple of its patch stride (14): the
        # predictor's feature sizes are 288/144/72, i.e. 72 * 14 = 1008.
        'imgsz':        1008,
    },
}

_cache = {}
_cache_lock = threading.Lock()


# ── Engine metadata ───────────────────────────────────────────────────────────

def _spec(engine):
    spec = ENGINES.get(str(engine or DEFAULT_ENGINE))
    if not spec:
        raise ModelError(f'Unknown prompt engine "{engine}".')
    return spec


def weights_path(engine=None) -> Path:
    """
    The checkpoint backing this engine.

    Searched across the same directories as Smart Detect's models, so a
    3 GB sam3.pt parked next to run.py counts as installed and does not
    have to be moved. Raises ModelError (→ 422) with the file it wants
    when there is none, because that is the whole remedy.
    """
    spec = _spec(engine)
    glob = spec['weights_glob']
    for d in SEARCH_DIRS:
        hits = sorted(d.glob(glob)) if d.exists() else []
        if hits:
            return hits[0]
    raise ModelError(
        f'{spec["label"]} needs a checkpoint. Place a file matching '
        f'"{glob}" in the models/ folder — it is not published as an '
        f'auto-downloadable asset, so it cannot be fetched for you.')


def list_engines() -> list:
    """
    Every engine plus whether it can run right now.

    The UI needs this to disable a prompt tab an engine cannot serve, to
    warn about a slow run before it starts, and to explain a missing
    checkpoint instead of failing at prompt time.
    """
    out = []
    for eid, spec in ENGINES.items():
        entry = {
            'id':          eid,
            'label':       spec['label'],
            'modes':       list(spec['modes']),
            'blurb':       spec['blurb'],
            'speed':       spec.get('speed', 'fast'),
            'download_mb': spec.get('download_mb'),
            'text_encoder': None,       # SAM3 carries its own, in-checkpoint
        }
        try:
            wp = weights_path(eid)
            entry['weights'] = wp.name
            entry['installed'] = True
            entry['error'] = None
        except ModelError as e:
            entry['weights'] = spec['weights_glob']
            entry['installed'] = False
            entry['error'] = str(e)
        out.append(entry)
    return out


# ── Loading ───────────────────────────────────────────────────────────────────

def _ensure_clip_tokenizer_callable():
    """
    Make SAM3 work with OpenAI's `clip` package.

    ultralytics builds SAM3's text encoder with
    `clip.simple_tokenizer.SimpleTokenizer()` and then CALLS that object.
    That only works with ultralytics' own CLIP fork. With OpenAI's `clip`
    installed instead — the common case, and what is installed here — the
    instance is not callable, and SAM3 dies deep inside its forward pass
    with "'SimpleTokenizer' object is not callable", for BOTH prompt types
    (a box prompt still encodes the pseudo-concept "visual").

    The two packages differ only in packaging: OpenAI's module-level
    `clip.tokenize` has exactly the signature the encoder wants. So teach
    the class to delegate to it. Guarded on the class's own `__call__`, so
    installing ultralytics' fork later turns this into a no-op rather than
    a conflict.
    """
    try:
        import clip
        from clip.simple_tokenizer import SimpleTokenizer
    except ImportError as e:
        raise ModelError(
            'SAM3 needs the CLIP tokenizer. Run: '
            'pip install git+https://github.com/ultralytics/CLIP.git'
        ) from e

    if '__call__' in vars(SimpleTokenizer):
        return                      # already callable — nothing to bridge
    if not hasattr(clip, 'tokenize'):
        raise ModelError(
            'The installed "clip" package is not OpenAI CLIP and cannot '
            'tokenize for SAM3. Run: '
            'pip install git+https://github.com/ultralytics/CLIP.git')

    # truncate=True: a long phrase should lose its tail, not raise.
    SimpleTokenizer.__call__ = (
        lambda self, text, context_length=77, truncate=True:
            clip.tokenize(text, context_length=context_length, truncate=truncate))


def load(engine=None):
    """Ready-to-run predictor for `engine`, built once and cached."""
    eid = str(engine or DEFAULT_ENGINE)
    spec = _spec(eid)
    path = weights_path(eid)

    try:
        st = path.stat()
    except OSError as e:
        raise ModelError(f'Cannot read "{path.name}": {e}') from e
    key = (eid, str(path.resolve()), st.st_mtime_ns, st.st_size)

    with _cache_lock:
        hit = _cache.get(key)
    if hit is not None:
        return hit

    _ensure_clip_tokenizer_callable()

    try:
        from ultralytics.models.sam import SAM3SemanticPredictor
    except ImportError as e:
        raise ModelError('ultralytics is not installed on the server. '
                         'Run: pip install ultralytics') from e

    try:
        inst = SAM3SemanticPredictor(overrides=dict(
            model=str(path), task='segment', mode='predict',
            conf=CONF_FLOOR, save=False, verbose=False,
            imgsz=spec.get('imgsz', 1008),
        ))
    except Exception as e:
        raise ModelError(
            f'"{path.name}" could not be loaded as a {spec["label"]} model: {e}'
        ) from e

    with _cache_lock:
        _cache[key] = inst
    return inst


# ── Result normalisation ──────────────────────────────────────────────────────

def _clamp01(v):
    return max(0.0, min(1.0, float(v)))


def _to_predictions(result, label_for) -> list:
    """
    ultralytics Results → the wire shape `api_ai_predict` already returns.

    `label_for(cls_id)` exists because a promptable model's class ids mean
    different things per mode: the index of the phrase for text prompts,
    the exemplar's concept for box prompts. The caller owns that mapping;
    this function only shapes the numbers.
    """
    out = []
    boxes = getattr(result, 'boxes', None)
    if boxes is None:
        return out
    for i in range(len(boxes)):
        cid = int(boxes.cls[i].item())
        xywhn = boxes.xywhn[i].tolist()
        out.append({
            'class_name':  label_for(cid),
            'yolo_cls_id': cid,
            'conf':        round(float(boxes.conf[i].item()), 4),
            'x_center':    round(_clamp01(xywhn[0]), 6),
            'y_center':    round(_clamp01(xywhn[1]), 6),
            'width':       round(_clamp01(xywhn[2]), 6),
            'height':      round(_clamp01(xywhn[3]), 6),
        })
    return out


# ── Prompt normalisation ──────────────────────────────────────────────────────

def clean_phrases(phrases) -> list:
    """De-duplicated, trimmed, order-preserving phrase list."""
    seen, out = set(), []
    for p in (phrases or []):
        s = str(p).strip()
        if not s:
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    if not out:
        raise ModelError('Enter at least one thing to look for, e.g. "person, helmet".')
    return out[:MAX_PHRASES]


def clean_exemplars(boxes) -> tuple:
    """
    Exemplar boxes → (xyxy in image pixels, per-box label index, labels).

    Boxes arrive in IMAGE PIXEL coordinates because that is what the canvas
    works in; normalising here would only have to be undone again.
    """
    xyxy, cls, labels = [], [], []
    for b in (boxes or [])[:MAX_EXEMPLARS]:
        try:
            x1, y1 = float(b['x1']), float(b['y1'])
            x2, y2 = float(b['x2']), float(b['y2'])
        except (KeyError, TypeError, ValueError):
            raise ModelError('Each example box needs numeric x1, y1, x2, y2.')
        if x2 - x1 < 2 or y2 - y1 < 2:
            continue                      # a stray click, not a box
        label = str(b.get('label') or 'object').strip() or 'object'
        if label not in labels:
            labels.append(label)
        xyxy.append([x1, y1, x2, y2])
        cls.append(labels.index(label))
    if not xyxy:
        raise ModelError('Draw at least one example box around the object to find.')
    return xyxy, cls, labels


# ── Prediction ────────────────────────────────────────────────────────────────

def _predict_sam3(predictor, img, mode, phrases, xyxy, labels, conf, iou):
    # SAM3's semantic head takes text and box exemplars through the SAME
    # call. Boxes take priority and, with no text alongside, are labelled
    # by the model as the generic "visual" concept — so we relabel from the
    # exemplars the user actually drew.
    predictor.args.conf = conf
    predictor.args.iou = iou
    kwargs = {}
    if mode == BOX:
        kwargs['bboxes'] = xyxy
        # One concept per call: SAM3 returns instances of the boxed
        # CONCEPT, so every hit belongs to the first exemplar's label.
        names = [labels[0]] if labels else ['object']
    else:
        kwargs['text'] = phrases
        names = phrases
    results = predictor(source=str(img), **kwargs)
    if not results:
        return []
    return _to_predictions(
        results[0],
        lambda cid: names[cid] if 0 <= cid < len(names)
        else (names[0] if names else 'object'))


def predict(image_path, engine=None, mode=TEXT, phrases=None, boxes=None,
            conf=CONF_FLOOR, iou=0.5) -> dict:
    """
    Run one prompted detection pass.

    Args:
        image_path: absolute path to the image, already existence-checked.
        engine:     key into ENGINES; None → DEFAULT_ENGINE ('sam3').
        mode:       TEXT or BOX.
        phrases:    words / short phrases (TEXT mode).
        boxes:      [{x1,y1,x2,y2,label}] in image pixels (BOX mode).
        conf:       floor, not the user's threshold — see module docstring.

    Returns {'predictions': [...], 'engine': ..., 'labels': [...]}.
    Raises ModelError (→ HTTP 422) for anything the user can act on.
    """
    eid = str(engine or DEFAULT_ENGINE)
    spec = _spec(eid)
    mode = BOX if mode == BOX else TEXT

    if mode not in spec['modes']:
        raise ModelError(
            f'{spec["label"]} does not support '
            f'{"box" if mode == BOX else "text"} prompting.')

    conf = max(0.01, min(0.99, float(conf)))
    iou = max(0.05, min(0.95, float(iou)))

    phrase_list, xyxy, labels = [], [], []
    if mode == TEXT:
        phrase_list = clean_phrases(phrases)
        labels = list(phrase_list)
    else:
        xyxy, _cls, labels = clean_exemplars(boxes)

    inst = load(eid)
    try:
        preds = _predict_sam3(inst, image_path, mode, phrase_list, xyxy,
                              labels, conf, iou)
    except ModelError:
        raise
    except Exception as e:
        raise ModelError(f'{spec["label"]} prompt failed: {e}') from e

    return {'predictions': preds, 'engine': eid, 'labels': labels}
