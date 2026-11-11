"""
FastAPI application factory.

Stage A0: boots, exposes /health (DB + Redis) and the auto-generated /docs.
Routers for auth/workspaces/etc. are mounted in later phases.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.db import ping as db_ping
from app.core.celery_app import redis_ping


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version='2.0.0-a0',
        debug=settings.debug,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,       # cookies carry the JWT, so credentials on
        allow_methods=['*'],
        allow_headers=['*'],
    )

    @app.get('/health', tags=['ops'])
    def health():
        """
        Liveness/readiness. Checks BOTH backing services this stack needs, the
        same principle as the original app's /health but extended to Redis
        because Celery depends on it. 200 only when both are up, else 503.
        """
        checks = {
            'database': 'ok' if db_ping() else 'error',
            'redis':    'ok' if redis_ping() else 'error',
        }
        ok = all(v == 'ok' for v in checks.values())
        url = settings.database_url
        return JSONResponse(
            {
                'status': 'ok' if ok else 'degraded',
                'checks': checks,
                # Proof of WHICH database is actually in use (password redacted).
                'database_backend': 'sqlite' if url.startswith('sqlite') else 'postgresql',
                'database_url': settings.redacted_database_url(),
            },
            status_code=200 if ok else 503,
        )

    # ── Routers (mounted as phases land) ─────────────────────────────────────
    from app.api import (
        ai, annotations, auth, datasets, locks, projects, uploads, workspaces,
    )
    app.include_router(auth.router, prefix='/api')
    app.include_router(workspaces.router, prefix='/api')
    app.include_router(projects.router, prefix='/api')
    app.include_router(uploads.router, prefix='/api')
    app.include_router(annotations.router, prefix='/api')
    app.include_router(locks.router, prefix='/api')
    app.include_router(ai.ai_router, prefix='/api')
    app.include_router(ai.ai_project_router, prefix='/api')
    app.include_router(datasets.router, prefix='/api')

    return app


app = create_app()
