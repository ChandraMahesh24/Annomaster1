"""
Database engine + session.

LAZY engine creation on purpose: the engine is built on first use, not at import
time, so importing the app never requires the Postgres driver to be installed or
the DB to be reachable. That keeps the app importable in environments without a
DB (CI collection, a machine mid-setup) and lets /health report "database down"
cleanly instead of crashing on import.

SQLAlchemy 2.0 typed style: models inherit from `Base` (DeclarativeBase).
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

_engine = None
_SessionLocal: sessionmaker[Session] | None = None


class Base(DeclarativeBase):
    """Declarative base for every ORM model."""


def _init():
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        url = settings.database_url

        # ── Loud guard: never run on SQLite by accident ──────────────────────
        # SQLite is only permitted when explicitly opted into (ALLOW_SQLITE=true)
        # for local dev. Otherwise a stray sqlite:// URL — or a missing
        # DATABASE_URL that somehow resolved to one — fails HERE with a clear
        # message, instead of silently running on the wrong database.
        if url.startswith('sqlite') and not settings.allow_sqlite:
            raise RuntimeError(
                'DATABASE_URL is SQLite but ALLOW_SQLITE is not set. SQLite is '
                'for explicit local dev only. Set a Postgres DATABASE_URL '
                '(postgresql+psycopg://…), or set ALLOW_SQLITE=true to opt in.'
            )
        import logging
        logging.getLogger('app').info(
            'Database backend: %s (%s)',
            'sqlite' if url.startswith('sqlite') else 'postgresql',
            settings.redacted_database_url(),
        )

        kwargs = dict(pool_pre_ping=True, future=True)
        # SQLite (used for local verification; Postgres is the real target) needs
        # a busy timeout or a second writer errors immediately instead of waiting
        # — the same hardening the original Flask app applied. No effect on PG.
        if url.startswith('sqlite'):
            kwargs['connect_args'] = {'timeout': 10, 'check_same_thread': False}
        else:
            # Postgres: fail FAST + loud when the server is unreachable (5s),
            # instead of hanging a request for the OS default (~2 min).
            kwargs['connect_args'] = {'connect_timeout': 5}
            kwargs['pool_timeout'] = 5
        _engine = create_engine(url, **kwargs)

        if url.startswith('sqlite'):
            from sqlalchemy import event

            @event.listens_for(_engine, 'connect')
            def _sqlite_pragmas(dbapi_conn, _):
                cur = dbapi_conn.cursor()
                cur.execute('PRAGMA foreign_keys=ON')   # enforce FKs / cascades
                cur.execute('PRAGMA busy_timeout=10000')
                cur.close()

        _SessionLocal = sessionmaker(
            bind=_engine, autoflush=False, autocommit=False, future=True
        )
    return _engine, _SessionLocal


def get_engine():
    return _init()[0]


def get_session() -> Iterator[Session]:
    """FastAPI dependency: yields a session, always closed."""
    _, SessionLocal = _init()
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ping() -> bool:
    """True if a trivial query succeeds. Used by /health. Never raises."""
    try:
        engine, _ = _init()
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
        return True
    except Exception:
        return False
