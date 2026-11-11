"""
Application settings — one typed source, loaded from environment / .env.

Pydantic-settings replaces the original app's scattered `os.environ.get(...)`
calls with a single validated object. Every value has a dev default so the app
boots without a .env, but production overrides them via real env vars.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env', env_file_encoding='utf-8', extra='ignore'
    )

    # ── App ──────────────────────────────────────────────────────────────────
    app_name: str = 'AnnoMaster'
    debug: bool = True

    # ── Security (ported: JWT via Bearer or cookie; 24h expiry) ──────────────
    secret_key: str = 'change-me-in-production'
    jwt_secret: str = 'change-me-in-production'
    jwt_algorithm: str = 'HS256'
    jwt_expiry_hours: int = 24

    # ── Postgres (the real target — "Postgres from day one") ─────────────────
    # Driver is psycopg 3 (sync) via SQLAlchemy: postgresql+psycopg://…
    # docker-compose provides this host/port; override via env in prod.
    database_url: str = (
        'postgresql+psycopg://annomaster:annomaster@localhost:5432/annomaster'
    )
    # SQLite is NOT a valid production database and must never be used by
    # accident. A `sqlite://` URL is rejected at startup UNLESS this flag is
    # explicitly set true (local dev without Docker). This turns a silent
    # wrong-database into a loud, opt-in choice.
    allow_sqlite: bool = False

    def redacted_database_url(self) -> str:
        """DATABASE_URL with the password masked — safe to log / show in /health."""
        import re
        return re.sub(r'(://[^:/@]+:)[^@]+(@)', r'\1***\2', self.database_url)

    # ── Redis / Celery broker + result backend ───────────────────────────────
    redis_url: str = 'redis://localhost:6379/0'
    celery_broker_url: str = 'redis://localhost:6379/1'
    celery_result_backend: str = 'redis://localhost:6379/2'

    # ── Filesystem-as-source-of-truth (ported layout convention) ─────────────
    # Absolute or relative; the paths service is the ONLY module that joins onto
    # this, exactly like the original app/core/paths.py rule.
    workspace_root: str = './workspace'
    models_dir: str = './models'

    # ── CORS (React dev server) ──────────────────────────────────────────────
    cors_origins: list[str] = ['http://localhost:5173']


@lru_cache
def get_settings() -> Settings:
    """Cached accessor — import this, never construct Settings() directly."""
    return Settings()
