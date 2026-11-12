"""
Compute-device selection for every AI model in the app (Smart Detect and
AI Annotate).

THE RULE
────────
Use the GPU when this machine has a usable one, otherwise the CPU — and
never surface a device problem to the user as an error. The same code has
to run unchanged on:

  • a laptop with an NVIDIA GPU and a CUDA build of torch,
  • a server with a CPU-only torch build (`torch.__version__` ends `+cpu`),
  • a machine with a GPU whose VRAM is too small for a given model.

HOW
───
`candidates()` lists the (device, half) configurations to try, best first:

    GPU present:  ('cuda:0', fp16) → ('cuda:0', fp32) → ('cpu', fp32)
    no GPU:       ('cpu', fp32)

`run(key, fn)` calls `fn(device, half)` down that list until one succeeds.
A configuration that fails for a non-memory reason (e.g. a model that does
not support fp16) is remembered per `key`, so the next request starts at
the one that worked instead of failing again first. CUDA out-of-memory is
NOT remembered: it can be transient (two requests at once), so the next
request tries the GPU again.

OVERRIDE
────────
`AI_DEVICE` env var: `auto` (default) | `cpu` | `cuda` | `cuda:N`.
`AI_HALF` env var:   `auto` (default, fp16 on GPU) | `0` (never fp16).
Forcing `cuda` on a machine without one degrades to CPU with a warning —
consistent with "never an error because of the device".
"""
import logging
import os
import threading

log = logging.getLogger(__name__)

_lock = threading.Lock()
_info = None            # resolved once: GPU availability cannot change at runtime
_start = {}             # key -> index into candidates() that last worked


def _torch():
    try:
        import torch
        return torch
    except Exception:           # not installed, or a broken install
        return None


def info() -> dict:
    """
    What this machine offers, resolved once per process.

    Returns {'device': 'cuda:0'|'cpu', 'gpu': bool, 'name': str,
             'vram_gb': float|None, 'torch': str|None, 'reason': str}.
    `reason` explains a CPU choice, so the UI can say WHY there is no GPU.
    """
    global _info
    if _info is not None:
        return _info

    want = (os.environ.get('AI_DEVICE') or 'auto').strip().lower()
    torch = _torch()
    out = {'device': 'cpu', 'gpu': False, 'name': 'CPU', 'vram_gb': None,
           'torch': getattr(torch, '__version__', None), 'reason': ''}

    if want == 'cpu':
        out['reason'] = 'AI_DEVICE=cpu'
    elif torch is None:
        out['reason'] = 'torch is not installed'
    else:
        try:
            ok = torch.cuda.is_available() and torch.cuda.device_count() > 0
        except Exception as e:
            ok = False
            out['reason'] = f'CUDA check failed: {e}'
        if not ok and not out['reason']:
            out['reason'] = ('torch is a CPU-only build'
                             if '+cpu' in out['torch'] else 'no CUDA GPU found')
        if ok:
            idx = 0
            if want.startswith('cuda:'):
                try:
                    idx = int(want.split(':', 1)[1])
                except ValueError:
                    idx = 0
            if idx >= torch.cuda.device_count():
                log.warning('AI_DEVICE=%s but only %d GPU(s); using cuda:0',
                            want, torch.cuda.device_count())
                idx = 0
            try:
                props = torch.cuda.get_device_properties(idx)
                out.update(device=f'cuda:{idx}', gpu=True, name=props.name,
                           vram_gb=round(props.total_memory / 1024 ** 3, 1))
            except Exception as e:
                out['reason'] = f'GPU unusable: {e}'

    if want.startswith('cuda') and not out['gpu']:
        log.warning('AI_DEVICE=%s requested but no usable GPU (%s); using CPU',
                    want, out['reason'])

    log.info('AI device: %s (%s)%s', out['device'], out['name'],
             f' - {out["reason"]}' if out['reason'] else '')
    _info = out
    return out


def candidates() -> list:
    """(device, half) configurations to try, best first."""
    i = info()
    if not i['gpu']:
        return [('cpu', False)]
    half_ok = (os.environ.get('AI_HALF') or 'auto').strip().lower() not in ('0', 'false', 'no')
    out = [(i['device'], True)] if half_ok else []
    out += [(i['device'], False), ('cpu', False)]
    return out


def is_oom(exc) -> bool:
    torch = _torch()
    oom_t = getattr(getattr(torch, 'cuda', None), 'OutOfMemoryError', None) if torch else None
    if oom_t and isinstance(exc, oom_t):
        return True
    return 'out of memory' in str(exc).lower()


def free_gpu():
    """Release cached VRAM after a failed GPU attempt, before falling back."""
    torch = _torch()
    try:
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def run(key, fn, reraise=()):
    """
    Call `fn(device, half)` on the best configuration that works.

    `reraise` — exception types that describe the INPUT, not the device
    (e.g. ModelError for a bad prompt). Those propagate at once: retrying
    a bad prompt on the CPU would only cost minutes and fail the same way.
    The last configuration's error propagates if every one fails.
    """
    cands = candidates()
    with _lock:
        first = min(_start.get(key, 0), len(cands) - 1)

    last_exc = None
    for i in range(first, len(cands)):
        device, half = cands[i]
        try:
            out = fn(device, half)
        except reraise:
            raise
        except Exception as e:
            last_exc = e
            oom = is_oom(e)
            if device != 'cpu':
                free_gpu()
            if i == len(cands) - 1:
                raise
            nxt = cands[i + 1]
            log.warning('%s failed on %s%s (%s) - retrying on %s%s',
                        key, device, ' fp16' if half else '',
                        'out of GPU memory' if oom else e,
                        nxt[0], ' fp16' if nxt[1] else '')
            if not oom:
                with _lock:
                    _start[key] = i + 1
            continue
        return out
    raise last_exc  # pragma: no cover — loop always returns or raises
