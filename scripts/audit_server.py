"""Disposable, loopback-only browser audit server. Never opens the live database.

Run from the repository root: python scripts/audit_server.py
Seeded login: audit@example.test / Audit-only-123!
Stop with Ctrl+C; the temporary workspace/database are removed on clean exit.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app, db
from config import Config
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.core.paths import ensure_project_dirs
from app.core.storage import save_project_meta


def main():
    with tempfile.TemporaryDirectory(prefix='annomaster-browser-audit-') as tmp:
        root = Path(tmp)

        class AuditConfig(Config):
            SQLALCHEMY_DATABASE_URI = 'sqlite:///' + (root / 'audit.db').as_posix()
            WORKSPACE_ROOT = root / 'workspace'
            SECRET_KEY = 'disposable-local-audit-secret-123456789'
            JWT_SECRET = SECRET_KEY
            RATELIMIT_ENABLED = False
            MAIL_SERVER = ''
            APP_BASE_URL = 'http://127.0.0.1:5055'

        app = create_app(AuditConfig)
        # Model uploads are isolated; existing checkpoints are read-only inputs.
        from app.core import ai_models
        from app.api import ai_annotate
        source_model_dirs = list(ai_models.SEARCH_DIRS)
        ai_models.MODELS_DIR = root / 'models'
        ai_models.MODELS_DIR.mkdir()
        ai_models.SEARCH_DIRS = [ai_models.MODELS_DIR, *source_model_dirs]
        ai_annotate.MODELS_DIR = ai_models.MODELS_DIR
        with app.app_context():
            user = User(username='Audit Owner', email='audit@example.test', public_id='USR-AUDIT')
            user.set_password('Audit-only-123!')
            db.session.add(user)
            for role in ('editor', 'viewer'):
                teammate = User(username='Audit '+role.title(), email=f'audit-{role}@example.test')
                teammate.set_password('Audit-only-123!')
                db.session.add(teammate)
            ws = Workspace(name='Audit Workspace', folder_name='WS-AUDIT', public_id='WS-AUDIT')
            db.session.add(ws)
            db.session.flush()
            db.session.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role='owner'))
            db.session.commit()
            ensure_project_dirs(ws.folder_name, 'audit-project')
            save_project_meta(ws.folder_name, 'audit-project', {
                'name': 'audit-project', 'description': 'Disposable audit fixtures',
                'classes': [{'id': 0, 'name': 'object', 'color': [34,197,94]}],
            })
            if '--fixtures' in sys.argv:
                import json
                from app.core.password_reset import make_token
                fixture_file = Path(sys.argv[sys.argv.index('--fixtures') + 1])
                fixture_file.write_text(json.dumps({'reset_token': make_token(user)}), encoding='utf-8')
        print('Disposable audit server: http://127.0.0.1:5055', flush=True)
        try:
            app.run(host='127.0.0.1', port=5055, debug=False, use_reloader=False)
        finally:
            from app.core.db_index import _ALL_CONNS, _CONNS_LOCK
            with _CONNS_LOCK:
                for conns in _ALL_CONNS.values():
                    for conn in conns:
                        conn.close()
                _ALL_CONNS.clear()
            with app.app_context():
                db.session.remove()
                db.engine.dispose()


if __name__ == '__main__':
    main()
