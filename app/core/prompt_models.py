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

from app.core import devices
from app.core.ai_models import SEARCH_DIRS, ModelError
from app.core.media import ALLOWED_IMG

TEXT = 'text'
BOX = 'box'

# The server always runs at this floor; the UI slider filters above it.
CONF_FLOOR = 0.05

# Guard rails on prompt size — every extra phrase is a pass through the
# text head, and every extra exemplar another visual embedding. With SAM3
# on CPU these are not theoretical: each one adds real seconds.
MAX_PHRASES = 20
MAX_PHRASE_LEN = 64       # matches what prompt settings persist
MAX_EXEMPLARS = 10

# Phrases are run through SAM3's grounding head this many at a time, against
# ONE cached image encoding. Memory grows steeply with the phrases in a single
# forward pass (25 at once tried to allocate 13.7 GB on CPU), and batching buys
# no speed — measured, 8 phrases on one 1920x1080 frame:
#   RTX 3050 6 GB, fp16:  batch 1 = 1.9 s / 2.75 GB · batch 2 = 4.3 s / 3.6 GB
#                         batch 4 = 11 s / 5.2 GB (near-full VRAM spills to
#                         system RAM under WDDM, which is what makes it slow)
#   CPU (4 phrases):      batch 1 = 33 s · batch 4 = 32 s
# So one phrase per pass: fastest on GPU, equal on CPU, lowest memory anywhere.
PHRASE_BATCH = 1

# One SAM3 predictor instance holds per-image state (`features`, the text
# classes it was last set to). Two requests interleaving on it would mix one
# image's features with another's prompt, so inference is serialised.
_run_lock = threading.Lock()

# Same set uploads accept, so anything in a project can be prompted.
IMAGE_EXTS = ALLOWED_IMG

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
        'blurb':        'Concept segmentation — text and box prompts.',
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
    dev = devices.info()
    for eid, spec in ENGINES.items():
        entry = {
            'id':          eid,
            'label':       spec['label'],
            'modes':       list(spec['modes']),
            'blurb':       spec['blurb'],
            # 'slow' is a CPU fact: on a GPU the same run takes seconds, and
            # warning "minutes per image" there would just be wrong.
            'speed':       'fast' if dev['gpu'] else spec.get('speed', 'fast'),
            'device':      dev['device'],
            'device_name': dev['name'],
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


def load(engine=None, device='cpu', half=False):
    """
    Ready-to-run predictor for `engine` on `device`, built once and cached.

    The device is part of the cache key: the CPU fallback (see
    core/devices.py) needs its own instance, because a predictor's model
    is moved onto its device the first time it runs.
    """
    eid = str(engine or DEFAULT_ENGINE)
    spec = _spec(eid)
    path = weights_path(eid)

    try:
        st = path.stat()
    except OSError as e:
        raise ModelError(f'Cannot read "{path.name}": {e}') from e
    key = (eid, str(path.resolve()), st.st_mtime_ns, st.st_size, device, bool(half))

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
            device=device, half=bool(half),
        ))
    except Exception as e:
        raise ModelError(
            f'"{path.name}" could not be loaded as a {spec["label"]} model: {e}'
        ) from e

    with _cache_lock:
        _cache[key] = inst
    return inst


def _evict(engine, device, half):
    """Drop a cached predictor — after it failed on the GPU, so its VRAM
    can be released before the CPU fallback runs."""
    eid = str(engine or DEFAULT_ENGINE)
    with _cache_lock:
        for k in [k for k in _cache if k[0] == eid and k[4] == device and k[5] == bool(half)]:
            del _cache[k]


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
    """
    De-duplicated, trimmed, order-preserving phrase list.

    Accepts a list, or one comma-separated string ("person, helmet") — the
    way people naturally type it. Anything else is rejected rather than
    iterated: iterating a dict or a bare string would silently prompt the
    model with its keys or single characters.

    Too many / too long is an ERROR, not a silent truncation, so the user
    is never left wondering why their 21st phrase found nothing.
    """
    if phrases is None:
        phrases = []
    elif isinstance(phrases, str):
        phrases = phrases.split(',')
    elif not isinstance(phrases, (list, tuple)):
        raise ModelError('Phrases must be a list like ["person", "helmet"].')

    seen, out = set(), []
    for p in phrases:
        if isinstance(p, (dict, list, tuple)):
            raise ModelError('Each phrase must be plain text.')
        s = ' '.join(str(p if p is not None else '').split())   # collapse whitespace
        if not s:
            continue
        if len(s) > MAX_PHRASE_LEN:
            raise ModelError(f'"{s[:30]}…" is too long — keep each phrase under '
                             f'{MAX_PHRASE_LEN} characters (a short noun works best).')
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    if not out:
        raise ModelError('Enter at least one thing to look for, e.g. "person, helmet".')
    if len(out) > MAX_PHRASES:
        raise ModelError(f'Too many phrases ({len(out)}) — use at most {MAX_PHRASES} per run.')
    return out


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

def read_image(path):
    """
    Decode an image to a BGR array, or raise ModelError saying why not.

    Done here rather than by ultralytics so a corrupt, empty or non-image
    file is a readable 422 ("could not be read as an image") instead of a
    loader stack trace. np.fromfile + imdecode also copes with non-ASCII
    Windows paths, which cv2.imread does not. IMREAD_COLOR normalises
    grayscale, RGBA and 16-bit inputs to 3-channel 8-bit.
    """
    import cv2
    import numpy as np
    try:
        buf = np.fromfile(str(path), dtype=np.uint8)
    except OSError as e:
        raise ModelError(f'Cannot read "{Path(path).name}": {e}') from e
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR) if buf.size else None
    if img is None or img.size == 0:
        raise ModelError(f'"{Path(path).name}" could not be read as an image — '
                         'the file is empty, corrupt, or not an image format.')
    return img


def _boxes_only(predictor, src_shape, chunk):
    """
    Boxes for one batch of phrases — (N, 6) tensor: xyxy pixels, score, class.

    `SAM3SemanticPredictor.inference_features()` does the same scoring, but also
    upsamples a full-resolution mask for EVERY hit and returns it. We never use
    masks (the app labels boxes), and that upsampling dominated GPU runs:
    measured on the RTX 3050, 8 phrases × a 1920×1080 frame = 466 masks →
    12 s and 5.6 of 6 GB VRAM. This mirrors its box path exactly (sigmoid ×
    presence score, `args.conf` threshold, class-offset NMS at `args.iou`)
    and skips the masks.

    It uses two private ultralytics methods, so if they move in an upgrade
    this falls back to the public call rather than breaking prompting.
    """
    import torch
    import torchvision
    from ultralytics.utils import ops

    if not (hasattr(predictor, '_inference_features')
            and hasattr(predictor, '_prepare_geometric_prompts')):
        _masks, boxes = predictor.inference_features(predictor.features, src_shape, text=chunk)
        return boxes

    h, w = src_shape
    with torch.inference_mode():
        prompts = predictor._prepare_geometric_prompts((h, w), None, None)
        preds = predictor._inference_features(predictor.features, *prompts, text=chunk)
        scores = (preds['pred_logits'].sigmoid()
                  * preds['presence_logit_dec'].sigmoid().unsqueeze(1)).squeeze(-1)
        cls = torch.arange(scores.shape[0], device=scores.device,
                           dtype=scores.dtype)[:, None].expand_as(scores)
        keep = scores > predictor.args.conf
        boxes = ops.xywh2xyxy(preds['pred_boxes'][keep].float())   # normalised
        score, cls = scores[keep].float(), cls[keep].float()
        if boxes.shape[0]:
            k = torchvision.ops.nms(boxes + cls[:, None] * 7680, score, predictor.args.iou)
            boxes, score, cls = boxes[k], score[k], cls[k]
        boxes = boxes * torch.tensor([w, h, w, h], device=boxes.device, dtype=boxes.dtype)
        return torch.cat([boxes, score[:, None], cls[:, None]], dim=1).cpu()


def _predict_text(predictor, img_path, phrases, conf, iou):
    """
    Text prompting: encode the image ONCE, then run the phrases through the
    text head in batches of PHRASE_BATCH. Returns the wire-shape predictions.
    """
    img = read_image(img_path)
    h, w = img.shape[:2]
    predictor.args.conf = conf
    predictor.args.iou = iou
    predictor.set_image(img)          # backbone runs here, once
    out = []
    try:
        for start in range(0, len(phrases), PHRASE_BATCH):
            chunk = phrases[start:start + PHRASE_BATCH]
            boxes = _boxes_only(predictor, (h, w), chunk)
            for row in boxes.tolist():          # xyxy px, score, cls-in-chunk
                x1, y1, x2, y2, score, cid = row
                x1, x2 = max(0.0, x1), min(float(w), x2)
                y1, y2 = max(0.0, y1), min(float(h), y2)
                if x2 - x1 < 1 or y2 - y1 < 1:
                    continue
                ci = int(cid)
                out.append({
                    'class_name':  chunk[ci] if 0 <= ci < len(chunk) else chunk[0],
                    'yolo_cls_id': start + ci,
                    'conf':        round(float(score), 4),
                    'x_center':    round(_clamp01((x1 + x2) / 2 / w), 6),
                    'y_center':    round(_clamp01((y1 + y2) / 2 / h), 6),
                    'width':       round(_clamp01((x2 - x1) / w), 6),
                    'height':      round(_clamp01((y2 - y1) / h), 6),
                })
    finally:
        predictor.reset_image()       # don't pin a frame's features in memory
    out.sort(key=lambda p: -p['conf'])
    return out


def _predict_sam3(predictor, img, mode, phrases, xyxy, labels, conf, iou):
    if mode == TEXT:
        return _predict_text(predictor, img, phrases, conf, iou)

    # BOX mode — unchanged path. SAM3's semantic head takes box exemplars
    # through the normal call; with no text alongside it labels hits as the
    # generic "visual" concept, so we relabel from the exemplars drawn.
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

    used = {}

    if mode == BOX:
        read_image(image_path)        # clean 422 for a corrupt file (text mode reads it anyway)

    def attempt(device, half):
        with _run_lock:
            inst = load(eid, device, half)
            try:
                out = _predict_sam3(inst, image_path, mode, phrase_list, xyxy,
                                    labels, conf, iou)
            except Exception:
                if device != 'cpu':
                    _evict(eid, device, half)
                raise
        used.update(device=device, half=half)
        return out

    # GPU when available, with automatic fallback to the CPU — see
    # core/devices.py. ModelError (bad prompt, missing weights) is about the
    # input, not the device, so it is not retried elsewhere.
    try:
        preds = devices.run(f'prompt:{eid}', attempt, reraise=(ModelError,))
    except ModelError:
        raise
    except Exception as e:
        raise ModelError(f'{spec["label"]} prompt failed: {e}') from e

    return {'predictions': preds, 'engine': eid, 'labels': labels,
            'device': used.get('device'), 'half': used.get('half')}


# ── Box prompting from a saved example library (Roboflow-style) ──────────────
#
# The per-image BOX mode above only works on the image the boxes were drawn on
# — SAM3's box prompts are officially same-image. This mode makes examples
# drawn on ANY image work on every image, in two steps chosen by measurement
# on project `m` (1_staff vs customer, 8 unseen frames, examples from 6 other
# frames):
#
#   1. FIND — each example box is encoded by SAM3's geometry encoder ON ITS
#      OWN image (that encoding pools the image features under the box), and
#      the resulting prompt tokens are fed to the grounding decoder for the
#      TARGET image, next to the generic "visual" concept. Found 92-95 % of
#      the people with no word given. (Pasting example crops into the target
#      instead found 38 %; the text prompt "person" found 49 %.)
#   2. WHICH CLASS — each hit is compared with every example by a feature
#      fingerprint (ROI-aligned SAM3 backbone features, 4x2 cells so upper vs
#      lower body is kept apart) and takes the class of its nearest POSITIVE
#      example. A nearer NEGATIVE example of that class vetoes it. 0.86
#      staff-vs-customer accuracy on true boxes; 0.76 with half the examples
#      — more examples, better classes.
#
# One grounding pass for all classes (one pass per class measured equal
# recall, lower precision for these look-alike classes, and costs N passes).

EXAMPLE_FP_LEVEL = 1          # backbone_fpn[1] = 144x144 for a 1008 input
_ex_cache = {}                # (id(inst), image, mtime, boxes) -> encoded
_EX_CACHE_MAX = 256


def _sam3_internals():
    try:
        from ultralytics.models.sam.sam3.sam3_image import SAM2Model
        from ultralytics.utils import ops
        return SAM2Model, ops
    except ImportError as e:
        raise ModelError('This ultralytics version cannot run example-based '
                         f'box prompting ({e}).') from e


def _prep_features(inst):
    SAM2Model, _ = _sam3_internals()
    return SAM2Model._prepare_backbone_features(inst.model, dict(inst.features), batch=1)


def _fingerprints(inst, boxes_px, W, H):
    """L2-normalised appearance vector per box, from the CURRENT image's features."""
    import torch
    import torch.nn.functional as F
    import torchvision
    feat = inst.features['backbone_fpn'][EXAMPLE_FP_LEVEL].float()
    fh, fw = feat.shape[-2:]
    rois = torch.tensor([[0, b[0] * fw / W, b[1] * fh / H, b[2] * fw / W, b[3] * fh / H]
                         for b in boxes_px], dtype=torch.float32, device=feat.device)
    r = torchvision.ops.roi_align(feat, rois, output_size=(4, 2), aligned=True).flatten(1)
    return F.normalize(r, dim=1).cpu()


def _encode_image_examples(inst, image_path, rows):
    """
    Encode every example drawn on one image: SAM3 prompt tokens (positives
    labelled 1, negatives 0) + fingerprints. Cached — the image and boxes
    rarely change, and re-encoding costs a backbone pass.
    """
    import torch
    try:
        mtime = Path(image_path).stat().st_mtime_ns
    except OSError:
        return None                               # example's image was deleted
    key = (id(inst), str(image_path), mtime,
           tuple((tuple(r['box']), bool(r['positive']), int(r['class_id'])) for r in rows))
    hit = _ex_cache.get(key)
    if hit is not None:
        return hit
    try:
        img = read_image(image_path)
    except ModelError:
        return None
    H, W = img.shape[:2]
    boxes = [[r['box'][0] * W, r['box'][1] * H, r['box'][2] * W, r['box'][3] * H] for r in rows]
    labs = [1 if r['positive'] else 0 for r in rows]
    inst.set_image(img)
    try:
        with torch.inference_mode():
            bb, ll = inst._prepare_geometric_prompts((H, W), boxes, labs)
            gp = inst._get_dummy_prompt(1)
            for i in range(len(bb)):
                gp.append_boxes(bb[[i]], ll[[i]])
            _, img_feats, pos, sizes = _prep_features(inst)
            tok, msk = inst.model._encode_prompt(img_feats, pos, sizes, gp)
            fps = _fingerprints(inst, boxes, W, H)
    finally:
        inst.reset_image()
    enc = {'tok': tok.clone(), 'msk': msk.clone(), 'fps': fps,
           'cls': [int(r['class_id']) for r in rows], 'pos': [bool(r['positive']) for r in rows]}
    if len(_ex_cache) >= _EX_CACHE_MAX:
        _ex_cache.pop(next(iter(_ex_cache)))
    _ex_cache[key] = enc
    return enc


def _ground_with_tokens(inst, H, W, tok, msk, conf, iou):
    """SAM3 grounding on the CURRENT image with example tokens from any image."""
    import torch
    import torchvision
    _, ops = _sam3_internals()
    m = inst.model
    with torch.inference_mode():
        if m.names != ['visual']:
            m.set_classes(['visual'])
        bo, img_feats, pos, sizes = _prep_features(inst)
        bo.update({k: v for k, v in m.text_embeddings.items()})
        ids = torch.tensor([0], device=tok.device)
        prompt = torch.cat([bo['language_features'][:, ids], tok], 0)
        pmask = torch.cat([bo['language_mask'][ids], msk], 1)
        enc = m._run_encoder(img_feats, pos, sizes, prompt, pmask)
        out, _hs = m._run_decoder(memory=enc['encoder_hidden_states'], pos_embed=enc['pos_embed'],
                                  src_mask=enc['padding_mask'], out={'backbone_out': bo},
                                  prompt=prompt, prompt_mask=pmask, encoder_out=enc)
        sc = (out['pred_logits'].sigmoid()
              * out['presence_logit_dec'].sigmoid().unsqueeze(1)).squeeze(-1)[0].float()
        bx = ops.xywh2xyxy(out['pred_boxes'][0].float())
        keep = sc > conf
        bx, sc = bx[keep], sc[keep]
        if len(bx):
            k = torchvision.ops.nms(bx, sc, iou)
            bx, sc = bx[k], sc[k]
        bx = bx * torch.tensor([W, H, W, H], device=bx.device, dtype=bx.dtype)
    return bx.cpu().tolist(), sc.cpu().tolist()


def _predict_from_examples(inst, image_path, groups, class_names, conf, iou):
    import torch
    encs = [e for e in (_encode_image_examples(inst, p, rows) for p, rows in groups) if e]
    if not encs or not any(any(e['pos']) for e in encs):
        raise ModelError('None of the saved examples could be used — their images '
                         'may have been deleted. Draw a new example.')
    tok = torch.cat([e['tok'] for e in encs], 0)
    msk = torch.cat([e['msk'] for e in encs], 1)
    fps = torch.cat([e['fps'] for e in encs], 0)
    ex_cls = torch.tensor(sum((e['cls'] for e in encs), []))
    ex_pos = torch.tensor(sum((e['pos'] for e in encs), []))

    img = read_image(image_path)
    H, W = img.shape[:2]
    inst.args.conf, inst.args.iou = conf, iou
    inst.set_image(img)
    try:
        boxes, scores = _ground_with_tokens(inst, H, W, tok, msk, conf, iou)
        if not boxes:
            return []
        sims = _fingerprints(inst, boxes, W, H) @ fps.T          # (hits, examples)
    finally:
        inst.reset_image()

    out = []
    pos_classes = sorted({c for c, p in zip(ex_cls.tolist(), ex_pos.tolist()) if p})
    for b, s, row in zip(boxes, scores, sims):
        best = {c: row[(ex_cls == c) & ex_pos].max().item() for c in pos_classes}
        c = max(best, key=best.get)
        neg = row[(ex_cls == c) & ~ex_pos]
        if len(neg) and neg.max().item() > best[c]:
            continue                                   # looks more like a "not this"
        x1, y1, x2, y2 = max(0.0, b[0]), max(0.0, b[1]), min(float(W), b[2]), min(float(H), b[3])
        if x2 - x1 < 1 or y2 - y1 < 1:
            continue
        out.append({
            'class_name':  class_names.get(c, f'class {c}'),
            'yolo_cls_id': c,
            'conf':        round(float(s), 4),
            'x_center':    round(_clamp01((x1 + x2) / 2 / W), 6),
            'y_center':    round(_clamp01((y1 + y2) / 2 / H), 6),
            'width':       round(_clamp01((x2 - x1) / W), 6),
            'height':      round(_clamp01((y2 - y1) / H), 6),
        })
    out.sort(key=lambda p: -p['conf'])
    return out


def predict_examples(image_path, examples, project_root, class_names,
                     engine=None, conf=CONF_FLOOR, iou=0.5) -> dict:
    """
    Predict on `image_path` from the project's saved example library.

    Args:
        examples:     rows from core/box_examples.load().
        project_root: project directory; example `image` paths are relative to it.
        class_names:  {class_id: name} — examples of a class the project no
                      longer has are ignored.
    Returns the same shape as predict(), plus 'examples_used'.
    """
    eid = str(engine or DEFAULT_ENGINE)
    spec = _spec(eid)
    if BOX not in spec['modes']:
        raise ModelError(f'{spec["label"]} does not support box prompting.')
    conf = max(0.01, min(0.99, float(conf)))
    iou = max(0.05, min(0.95, float(iou)))

    rows = [r for r in (examples or []) if int(r.get('class_id', -1)) in class_names]
    if not any(r.get('positive', True) for r in rows):
        raise ModelError('No examples yet — draw a box around an object and pick its '
                         'class to teach the model what to find.')
    root = Path(project_root).resolve()
    groups = {}
    for r in rows:
        p = (root / r['image']).resolve()
        if p.is_relative_to(root):                 # a hand-edited "../" never escapes
            groups.setdefault(str(p), []).append(r)
    read_image(image_path)                         # clean 422 for a corrupt target

    used = {}

    def attempt(device, half):
        with _run_lock:
            inst = load(eid, device, half)
            if inst.model is None:                 # SAM3 builds lazily on first image
                inst.setup_model()
            try:
                out = _predict_from_examples(inst, image_path, list(groups.items()),
                                             class_names, conf, iou)
            except Exception:
                if device != 'cpu':
                    _evict(eid, device, half)
                raise
        used.update(device=device, half=half)
        return out

    try:
        preds = devices.run(f'prompt:{eid}', attempt, reraise=(ModelError,))
    except ModelError:
        raise
    except Exception as e:
        raise ModelError(f'{spec["label"]} example prompt failed: {e}') from e
    labels = sorted({class_names[int(r['class_id'])] for r in rows if r.get('positive', True)})
    return {'predictions': preds, 'engine': eid, 'labels': labels,
            'examples_used': len(rows), 'device': used.get('device'), 'half': used.get('half')}
