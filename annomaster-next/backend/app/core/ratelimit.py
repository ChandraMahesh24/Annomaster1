"""
Fixed-window rate limiter as a FastAPI dependency.

The original used flask-limiter. slowapi (its FastAPI analogue) isn't installed
on this box, and the rules are simple, so this is a small built-in limiter with
a swappable backend:

  • Redis when reachable — a shared counter (INCR + EXPIRE) that holds across
    multiple uvicorn workers, which is the ONLY correct way to rate-limit a
    multi-process server.
  • in-memory fallback otherwise — fine for a single-process dev server, and
    what lets this be verified here without Redis.

A limit is (max_hits, window_seconds). A route can carry several
(login = 15/min AND 60/hr), and ALL must pass.
"""

import time
from collections import defaultdict

from fastapi import HTTPException, Request, status

from app.core.config import get_settings

# ── in-memory backend (dev / no-Redis) ───────────────────────────────────────
_mem: dict[str, list[float]] = defaultdict(list)


def _hit_memory(key: str, limit: int, window: int) -> bool:
    now = time.time()
    bucket = _mem[key]
    cutoff = now - window
    # drop timestamps outside the window, then count
    bucket[:] = [t for t in bucket if t > cutoff]
    if len(bucket) >= limit:
        return False
    bucket.append(now)
    return True


# ── Redis backend (prod / multi-worker) ───────────────────────────────────────
_redis = None
_redis_tried = False


def _get_redis():
    global _redis, _redis_tried
    if _redis_tried:
        return _redis
    _redis_tried = True
    try:
        import redis
        client = redis.Redis.from_url(
            get_settings().redis_url, socket_connect_timeout=1)
        client.ping()
        _redis = client
    except Exception:
        _redis = None
    return _redis


def _hit_redis(client, key: str, limit: int, window: int) -> bool:
    # Fixed window: one counter per (key, window-bucket). INCR then set TTL on
    # first hit. Atomic enough for rate limiting; no Lua needed.
    bucket = int(time.time()) // window
    rk = f'rl:{key}:{window}:{bucket}'
    n = client.incr(rk)
    if n == 1:
        client.expire(rk, window)
    return n <= limit


class RateLimiter:
    """Dependency factory: RateLimiter('login', [(15,60),(60,3600)])."""

    def __init__(self, name: str, limits: list[tuple[int, int]]):
        self.name = name
        self.limits = limits

    def __call__(self, request: Request) -> None:
        ip = request.client.host if request.client else 'unknown'
        client = _get_redis()
        for limit, window in self.limits:
            key = f'{self.name}:{ip}'
            ok = (_hit_redis(client, key, limit, window) if client
                  else _hit_memory(f'{key}:{window}', limit, window))
            if not ok:
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f'Rate limit exceeded ({limit} per {window}s). Try again later.',
                )


# Ported limits (login 15/min·60/hr, register 10/hr, pw-change 5/hr).
login_limit    = RateLimiter('login',    [(15, 60), (60, 3600)])
register_limit = RateLimiter('register', [(10, 3600)])
pwchange_limit = RateLimiter('pwchange', [(5, 3600)])
