"""
Prove which database is actually in use, and that the tables exist there.

Run this AFTER `alembic upgrade head` against your real Postgres:

    python scripts/verify_db.py

It's a `psql \dt`/`SELECT * FROM alembic_version` substitute (psql may not be
installed) that connects through the SAME settings the app uses, so what it
reports is exactly what the app will use.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.db import get_engine  # noqa: E402


def main() -> int:
    s = get_settings()
    backend = 'sqlite' if s.database_url.startswith('sqlite') else 'postgresql'
    print(f'Resolved DATABASE_URL : {s.redacted_database_url()}')
    print(f'Backend               : {backend}')
    if backend != 'postgresql':
        print('\n[!] Not Postgres. Point DATABASE_URL at Postgres (unset ALLOW_SQLITE).')
        return 1

    try:
        eng = get_engine()
        with eng.connect() as c:
            ver = c.execute(text('SELECT version()')).scalar()
            print(f'Server                : {ver.split(",")[0]}')
            alembic = c.execute(text('SELECT version_num FROM alembic_version')).scalar()
        tables = sorted(inspect(eng).get_table_names())
        print(f'alembic_version       : {alembic}')
        print(f'Tables ({len(tables)})           : {", ".join(tables)}')
        expected = {'users', 'workspaces', 'workspace_members', 'images',
                    'upload_batches', 'assignments', 'annotation_locks', 'audit_log'}
        missing = expected - set(tables)
        if missing:
            print(f'\n[!] MISSING tables: {missing} — run `alembic upgrade head`.')
            return 1
        print('\nOK: Postgres is in use and all 8 tables exist.')
        return 0
    except Exception as e:
        print(f'\n[!] Could NOT connect/inspect Postgres: {type(e).__name__}: {e}')
        print('    Is Postgres running? (docker compose up -d, or a native server)')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
