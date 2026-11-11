"""
Celery application.

The three long-running jobs the original ran synchronously and shouldn't have —
Smart Detect inference, dataset ZIP export, and ffmpeg frame extraction — are
background tasks here from day one (Phase B builds the actual task bodies). This
module just wires the app to the Redis broker/backend.

Import is guarded so the API can boot for /health even when Celery isn't
installed yet (it isn't on the current dev box); the worker process is what
truly needs it.
"""
from app.core.config import get_settings

settings = get_settings()

try:
    from celery import Celery

    celery_app = Celery(
        'annomaster',
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=['app.workers.tasks'],
    )
    celery_app.conf.update(
        task_track_started=True,
        task_time_limit=60 * 15,       # 15 min hard cap (matches ffmpeg timeout)
        result_expires=60 * 60,
        worker_max_tasks_per_child=50,  # recycle workers holding YOLO models
    )
    CELERY_AVAILABLE = True
except ImportError:
    celery_app = None
    CELERY_AVAILABLE = False


def redis_ping() -> bool:
    """True if Redis answers. Used by /health. Never raises."""
    try:
        import redis
        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1)
        return bool(client.ping())
    except Exception:
        return False
