"""
Background tasks. The three jobs the original ran synchronously and shouldn't
have: video frame extraction (here), Smart Detect inference (B3), ZIP export
(B4).

Each has a plain SERVICE function (the real work) and a thin Celery wrapper.
Splitting them this way means the logic is testable without a broker, and the
endpoint can run it inline when Celery/Redis aren't available (dev) or enqueue
it when they are (prod) — same code path either way.
"""
import subprocess
from pathlib import Path

from app.core import paths
from app.core.celery_app import CELERY_AVAILABLE, celery_app


def extract_frames_service(folder: str, project: str, job_name: str,
                           video_path: str, stem: str, fps: int,
                           fmt: str = 'jpg', size: str = 'original') -> int:
    """
    Extract frames with ffmpeg into the batch's images dir. Returns the count.
    `fmt` is 'jpg'|'png'; `size` is 'original'|'1080p'|'720p'|'480p' — matching
    the original app's Video → Frame Extraction settings. ffmpeg must be on PATH.
    """
    ext = 'png' if str(fmt).lower() == 'png' else 'jpg'
    img_dir = paths.batch_img_dir(folder, project, job_name)
    img_dir.mkdir(parents=True, exist_ok=True)
    out_pat = str(img_dir / f'{stem}_frame%06d.{ext}')

    vf = [f'fps={fps}']
    heights = {'1080p': 1080, '720p': 720, '480p': 480}
    if size in heights:
        vf.append(f'scale=-2:{heights[size]}')      # keep aspect, even width
    cmd = ['ffmpeg', '-y', '-i', video_path, '-vf', ','.join(vf), '-vsync', 'vfr']
    cmd += (['-q:v', '2'] if ext == 'jpg' else []) + ['-threads', '0', out_pat]

    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=600)
    except FileNotFoundError:
        raise RuntimeError('ffmpeg not found on PATH — install it for video support.')
    except subprocess.TimeoutExpired:
        raise RuntimeError('Video extraction timed out (>10 min).')

    saved = sum(1 for f in img_dir.iterdir()
                if f.suffix.lower() == f'.{ext}' and f.stem.startswith(stem + '_frame'))
    if saved == 0 and proc.returncode != 0:
        raise RuntimeError(f'ffmpeg could not decode this video: '
                           f'{proc.stderr.decode(errors="ignore")[-200:]}')
    return saved


def predict_service(model_name: str, image_path: str, conf: float) -> list[dict]:
    """
    Run YOLO inference on one image → normalized boxes. Uses the cached model
    instance (services.ai_models), so only the first call per model pays the
    ~8s load. Below-`conf` detections are dropped by ultralytics before they
    reach here. Raises ModelError on an unusable model.
    """
    from app.services.ai_models import load
    model = load(model_name)                       # cached; ModelError if bad
    results = model.predict(image_path, conf=conf, verbose=False)
    preds: list[dict] = []
    if results:
        boxes = results[0].boxes
        names = results[0].names
        if boxes is not None:
            for i in range(len(boxes)):
                cls_id = int(boxes.cls[i].item())
                xywhn = boxes.xywhn[i].tolist()
                preds.append({
                    'class_name': names.get(cls_id, str(cls_id)),
                    'yolo_cls_id': cls_id,
                    'conf': round(float(boxes.conf[i].item()), 4),
                    'x_center': round(xywhn[0], 6), 'y_center': round(xywhn[1], 6),
                    'width': round(xywhn[2], 6), 'height': round(xywhn[3], 6),
                })
    return preds


def export_zip_service(fmt: str, items: list, class_names: list, pdir_str: str,
                       out_path: str) -> str:
    """Build an export ZIP to out_path and return it. Confirmed-only by
    construction (items come from .txt / a frozen version manifest)."""
    from app.services.exports import build_zip
    data = build_zip(fmt, items, class_names, Path(pdir_str))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_bytes(data)
    return out_path


if CELERY_AVAILABLE:
    @celery_app.task(name='extract_frames')
    def extract_frames_task(folder, project, job_name, video_path, stem, fps,
                            fmt='jpg', size='original'):
        return extract_frames_service(folder, project, job_name, video_path,
                                      stem, fps, fmt, size)

    @celery_app.task(name='predict')
    def predict_task(model_name, image_path, conf):
        return predict_service(model_name, image_path, conf)

    @celery_app.task(name='export_zip')
    def export_zip_task(fmt, items, class_names, pdir_str, out_path):
        return export_zip_service(fmt, items, class_names, pdir_str, out_path)
else:
    extract_frames_task = None
    predict_task = None
    export_zip_task = None
