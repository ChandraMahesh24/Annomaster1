from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import logging

db      = SQLAlchemy()
migrate = Migrate()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],          # no global limit — only per-route decorators
    storage_uri="memory://",    # in-process; swap for "redis://..." in production
)

log = logging.getLogger(__name__)


def create_app(config_class=None):
    from config import Config
    if config_class is None:
        config_class = Config

    app = Flask(__name__, template_folder='../templates', static_folder='../static')
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)

    # ── SQLite hardening — enforce FKs, enable WAL for concurrency ────────────
    _setup_sqlite_pragmas(app)

    # Ensure workspace root exists
    config_class.WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

    # ── Register API blueprints ───────────────────────────────────────────────
    from app.api.auth       import auth_bp
    from app.api.workspace  import workspace_bp
    from app.api.projects   import projects_bp
    from app.api.media      import media_bp
    from app.api.annotations import annotations_bp
    from app.api.classes    import classes_bp
    from app.api.uploads    import uploads_bp
    from app.api.datasets   import datasets_bp
    from app.api.versions   import versions_bp
    from app.api.ai_annotate import ai_annotate_bp
    from app.api.locks      import locks_bp
    from app.api.audit      import audit_bp
    from app.api.user_stats import stats_bp

    for bp in [
        auth_bp, workspace_bp, projects_bp, media_bp, annotations_bp,
        classes_bp, uploads_bp, datasets_bp, versions_bp, ai_annotate_bp,
        locks_bp, audit_bp, stats_bp,
    ]:
        app.register_blueprint(bp)

    # ── Create all tables (including new models) ──────────────────────────────
    with app.app_context():
        from app.models.user            import User            # noqa: F401
        from app.models.workspace       import Workspace, WorkspaceMember  # noqa: F401
        from app.models.audit_log       import AuditLog        # noqa: F401
        from app.models.annotation_lock import AnnotationLock  # noqa: F401
        from app.models.upload_batch    import UploadBatch     # noqa: F401
        from app.models.image           import Image           # noqa: F401
        from app.models.assignment      import Assignment      # noqa: F401
        db.create_all()

    # ── Startup health check ──────────────────────────────────────────────────
    _check_workspace_health(app)

    _register_page_routes(app)
    _register_health(app)
    _register_asset_helper(app)
    return app


def _register_asset_helper(app):
    """`asset('css/tokens.css')` → `/static/css/tokens.css?v=<mtime>`.

    Used by templates/layout/head_assets.html so a stylesheet or script change
    reaches browsers on the next normal reload, without hand-editing ?v= strings
    in every template (stale cached CSS was a repeated audit finding).
    """
    import os

    @app.template_global('asset')
    def asset(path):
        full = os.path.join(app.static_folder, path)
        try:
            version = int(os.path.getmtime(full))
        except OSError:
            version = 0
        return f'/static/{path}?v={version}'


def _register_health(app):
    """
    Liveness/readiness probe. Unauthenticated on purpose so a load balancer or
    uptime monitor can hit it. Checks BOTH sources of truth this app depends on:

      • SQLite   — runs a trivial query on a real pooled connection, so a
                   locked/corrupt/permission-denied DB fails the probe rather
                   than only failing later inside a request.
      • workspace root — stat()s the directory that every image/label path is
                   built on. It is as load-bearing as the database (all
                   annotation data lives under it), and an unmounted volume or
                   revoked permission there is invisible to a DB-only check.

    Returns 200 only when both are healthy, 503 otherwise, so it can gate
    traffic. Never leaks internals — just ok/degraded per subsystem.
    """
    from flask import jsonify
    from sqlalchemy import text

    @app.route('/favicon.ico')
    def favicon():
        return app.send_static_file('favicon.svg')

    @app.route('/health')
    def health():
        checks = {'database': 'ok', 'workspace_root': 'ok'}
        ok = True

        try:
            db.session.execute(text('SELECT 1'))
        except Exception:
            checks['database'] = 'error'
            ok = False
        finally:
            db.session.remove()

        try:
            root = app.config['WORKSPACE_ROOT']
            if not (root.exists() and root.is_dir()):
                checks['workspace_root'] = 'missing'
                ok = False
        except Exception:
            checks['workspace_root'] = 'error'
            ok = False

        return jsonify({'status': 'ok' if ok else 'degraded', 'checks': checks}), \
            (200 if ok else 503)


def _setup_sqlite_pragmas(app):
    """
    Configure SQLite for production use on every new connection:
      - foreign_keys=ON  → enforce FK constraints (SQLite ignores them by default!)
      - journal_mode=WAL → allow concurrent reads during writes
      - busy_timeout=5000 → wait 5s instead of immediate SQLITE_BUSY error
    """
    from sqlalchemy import event

    with app.app_context():
        @event.listens_for(db.engine, 'connect')
        def _on_connect(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute('PRAGMA foreign_keys = ON')
            cursor.execute('PRAGMA journal_mode = WAL')
            cursor.execute('PRAGMA busy_timeout = 5000')
            cursor.close()


def _check_workspace_health(app):
    """Detect and log orphan workspaces on startup (DB record but no disk folder)."""
    with app.app_context():
        from app.models.workspace import Workspace
        from app.core.paths import workspace_dir
        orphans = []
        for ws in Workspace.query.all():
            if not workspace_dir(ws.folder_name).exists():
                orphans.append(
                    f"  id={ws.id} public_id={ws.public_id} "
                    f"name='{ws.name}' folder='{ws.folder_name}'"
                )
        if orphans:
            log.warning(
                'Found %d workspace(s) with no disk folder:\n%s',
                len(orphans), '\n'.join(orphans)
            )


def _register_page_routes(app):
    """
    All HTML page routes — now protected by server-side JWT check.
    Unauthenticated requests are redirected to /login instead of being served.
    The JS still does a client-side redirect too, giving a belt-and-suspenders
    approach to access control.
    """
    from flask import render_template, redirect
    from app.utils.security import get_current_user

    def _require_auth():
        """Return None when the request is authenticated, else a redirect."""
        user = get_current_user()
        if not user or not user.is_active:
            return redirect('/login')
        return None

    @app.route('/')
    def index():
        r = _require_auth(); return r if r else render_template('workspace/dashboard.html')

    @app.route('/pages/upload')
    def upload_page():
        r = _require_auth()
        if r:
            return r
        # The legacy template loads the canvas engine without a canvas. Keep
        # old links working by using the maintained project upload section.
        from flask import request
        from urllib.parse import urlencode
        return redirect('/pages/annotate?' + urlencode(request.args) + '#upload')

    @app.route('/pages/annotate')
    def annotate_page():
        r = _require_auth(); return r if r else render_template('pages/annotate.html')

    @app.route('/workspace/<int:workspace_id>/members')
    def members_page(workspace_id):
        r = _require_auth(); return r if r else render_template('workspace/members.html')

    @app.route('/settings')
    def settings_page():
        r = _require_auth(); return r if r else render_template('pages/settings.html')
