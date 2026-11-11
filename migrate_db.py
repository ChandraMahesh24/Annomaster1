"""
Database migration script.

Run after any upgrade that adds new tables or columns:
    python migrate_db.py

What it does:
  - Adds new columns to the existing `users` table (SQLite ALTER TABLE)
  - Creates tables: audit_log, annotation_locks, upload_batches, images, assignments
  - Safe to run multiple times — skips columns/tables that already exist
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / 'annomaster.db'

if not DB_PATH.exists():
    print(f"[ERROR] Database not found at {DB_PATH}")
    print("  Start the app once first so db.create_all() builds the base schema.")
    raise SystemExit(1)

conn = sqlite3.connect(str(DB_PATH))
cur  = conn.cursor()


# ── Helper ─────────────────────────────────────────────────────────────────────

def column_exists(table: str, column: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())

def table_exists(table: str) -> bool:
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cur.fetchone() is not None

def add_column(table: str, column: str, definition: str):
    if column_exists(table, column):
        print(f"  [SKIP] {table}.{column} already exists")
    else:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        print(f"  [ADD]  {table}.{column}")


# ── 1. New columns on `users` ──────────────────────────────────────────────────

print("\n[1/3] Patching users table ...")
add_column('users', 'avatar_url',         'VARCHAR(500)')
add_column('users', 'bio',                'VARCHAR(500)')
add_column('users', 'updated_at',         'DATETIME')
add_column('users', 'last_login',         'DATETIME')
add_column('users', 'failed_login_count', 'INTEGER NOT NULL DEFAULT 0')
add_column('users', 'locked_until',       'DATETIME')


# ── 2. Create `audit_log` ──────────────────────────────────────────────────────

print("\n[2/3] Creating audit_log table ...")
if table_exists('audit_log'):
    print("  [SKIP] audit_log already exists")
else:
    cur.execute("""
        CREATE TABLE audit_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER REFERENCES users(id) ON DELETE SET NULL,
            action        VARCHAR(80)  NOT NULL,
            workspace_id  INTEGER,
            project       VARCHAR(200),
            image_path    TEXT,
            detail        TEXT,
            ip_address    VARCHAR(50),
            timestamp     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX ix_audit_workspace_project ON audit_log(workspace_id, project)")
    cur.execute("CREATE INDEX ix_audit_user_id           ON audit_log(user_id)")
    cur.execute("CREATE INDEX ix_audit_timestamp         ON audit_log(timestamp)")
    cur.execute("CREATE INDEX ix_audit_action            ON audit_log(action)")
    print("  [OK]  audit_log created with 4 indexes")


# ── 3. Create `annotation_locks` ──────────────────────────────────────────────

print("\n[3/3] Creating annotation_locks table ...")
if table_exists('annotation_locks'):
    print("  [SKIP] annotation_locks already exists")
else:
    cur.execute("""
        CREATE TABLE annotation_locks (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id  INTEGER  NOT NULL,
            project       VARCHAR(200) NOT NULL,
            image_path    TEXT     NOT NULL,
            locked_by     INTEGER  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            acquired_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            expires_at    DATETIME NOT NULL,
            UNIQUE (workspace_id, project, image_path)
        )
    """)
    cur.execute("CREATE INDEX ix_lock_expires           ON annotation_locks(expires_at)")
    cur.execute("CREATE INDEX ix_lock_workspace_project ON annotation_locks(workspace_id, project)")
    print("  [OK]  annotation_locks created with 2 indexes")


# ── 4. Create `upload_batches` ────────────────────────────────────────────────

print("\n[4/6] Creating upload_batches table ...")
if table_exists('upload_batches'):
    print("  [SKIP] upload_batches already exists")
else:
    cur.execute("""
        CREATE TABLE upload_batches (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id  INTEGER  NOT NULL,
            project       VARCHAR(200) NOT NULL,
            batch_name    VARCHAR(200),
            source        VARCHAR(50)  NOT NULL DEFAULT 'upload',
            uploaded_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
            uploaded_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            total_images  INTEGER  NOT NULL DEFAULT 0
        )
    """)
    cur.execute("CREATE INDEX ix_batch_workspace_project ON upload_batches(workspace_id, project)")
    cur.execute("CREATE INDEX ix_batch_uploaded_by       ON upload_batches(uploaded_by)")
    print("  [OK]  upload_batches created with 2 indexes")


# ── 5. Create `images` ────────────────────────────────────────────────────────

print("\n[5/6] Creating images table (+ patch missing columns) ...")
if table_exists('images'):
    print("  [EXISTS] images — checking for missing columns ...")
    add_column('images', 'added_to_dataset_at', 'DATETIME')
else:
    cur.execute("""
        CREATE TABLE images (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id  INTEGER  NOT NULL,
            project       VARCHAR(200) NOT NULL,
            batch_id      INTEGER REFERENCES upload_batches(id) ON DELETE SET NULL,
            filename      VARCHAR(500) NOT NULL,
            rel_path      TEXT     NOT NULL,

            status        VARCHAR(20)  NOT NULL DEFAULT 'active',
            split         VARCHAR(10),

            is_annotated  BOOLEAN  NOT NULL DEFAULT 0,
            is_null       BOOLEAN  NOT NULL DEFAULT 0,

            uploaded_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
            uploaded_at   DATETIME DEFAULT CURRENT_TIMESTAMP,

            annotated_by         INTEGER REFERENCES users(id) ON DELETE SET NULL,
            annotated_at         DATETIME,

            reviewed_by          INTEGER REFERENCES users(id) ON DELETE SET NULL,
            reviewed_at          DATETIME,
            added_to_dataset_at  DATETIME,

            assigned_to          INTEGER REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    cur.execute("CREATE INDEX ix_image_workspace_project ON images(workspace_id, project)")
    cur.execute("CREATE INDEX ix_image_batch_id          ON images(batch_id)")
    cur.execute("CREATE INDEX ix_image_status            ON images(status)")
    cur.execute("CREATE INDEX ix_image_annotated_by      ON images(annotated_by)")
    cur.execute("CREATE INDEX ix_image_assigned_to       ON images(assigned_to)")
    print("  [OK]  images created with 5 indexes")


# ── 6. Create `assignments` ───────────────────────────────────────────────────

print("\n[6/6] Creating assignments table ...")
if table_exists('assignments'):
    print("  [SKIP] assignments already exists")
else:
    cur.execute("""
        CREATE TABLE assignments (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id  INTEGER  NOT NULL,
            project       VARCHAR(200) NOT NULL,
            batch_id      INTEGER REFERENCES upload_batches(id) ON DELETE CASCADE,
            assigned_to   INTEGER  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            assigned_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
            assigned_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            due_date      DATETIME,
            note          TEXT,
            status        VARCHAR(20) NOT NULL DEFAULT 'pending',
            total_images  INTEGER  NOT NULL DEFAULT 0,
            done_images   INTEGER  NOT NULL DEFAULT 0
        )
    """)
    cur.execute("CREATE INDEX ix_assignment_workspace_project ON assignments(workspace_id, project)")
    cur.execute("CREATE INDEX ix_assignment_assigned_to       ON assignments(assigned_to)")
    cur.execute("CREATE INDEX ix_assignment_batch_id          ON assignments(batch_id)")
    cur.execute("CREATE INDEX ix_assignment_status            ON assignments(status)")
    print("  [OK]  assignments created with 4 indexes")


# ── 7. Schema-integrity guards (enum CHECKs + uniqueness) ─────────────────────
#
# SQLite has NO `ALTER TABLE ... ADD CONSTRAINT`, so a CHECK cannot be added to
# an existing column without a full 12-step table rebuild (create-new / copy /
# drop / rename). That is riskier than this app's raw-ALTER migration style
# warrants, so enum values are enforced with BEFORE INSERT/UPDATE TRIGGERS
# instead — same guarantee at write time, and `CREATE TRIGGER IF NOT EXISTS`
# keeps it idempotent.
#
# The allowed sets below were taken from the DISTINCT values actually present
# in a live DB, NOT from the model docstrings — the images.split docstring says
# 'train|val|test' but the real data (and the dataset builder) use
# 'train|valid|test'. A CHECK copied from the docstring would reject valid rows.

print("\n[7/8] Adding enum-guard triggers (idempotent) ...")

def add_enum_trigger(table, column, allowed, allow_null=True):
    allowed_sql = ', '.join(f"'{v}'" for v in allowed)
    null_ok = f"NEW.{column} IS NOT NULL AND " if allow_null else ""
    for op in ('INSERT', 'UPDATE'):
        name = f"trg_{table}_{column}_{op.lower()}"
        cur.execute(f"""
            CREATE TRIGGER IF NOT EXISTS {name}
            BEFORE {op} ON {table}
            FOR EACH ROW WHEN {null_ok}NEW.{column} NOT IN ({allowed_sql})
            BEGIN
                SELECT RAISE(ABORT, 'invalid {table}.{column}');
            END;
        """)
    print(f"  [OK]  {table}.{column} in ({allowed_sql})")

# images.status is NOT NULL; split is nullable (only set once in a dataset).
add_enum_trigger('images', 'status', ('active', 'in_dataset'), allow_null=False)
add_enum_trigger('images', 'split',  ('train', 'valid', 'test'), allow_null=True)
add_enum_trigger('assignments', 'status',
                 ('pending', 'in_progress', 'submitted', 'approved', 'rejected'),
                 allow_null=False)


# ── 8. Uniqueness that must hold at the DATA layer (races beat app checks) ─────
#
# App-level "check then insert" guards race under concurrency; only a DB
# constraint is authoritative. These are all idempotent (IF NOT EXISTS) and
# wrapped so a pre-existing duplicate is REPORTED rather than crashing the
# whole migration.

print("\n[8/8] Adding uniqueness indexes (idempotent) ...")

def add_unique_index(name, table, cols, where=None):
    where_sql = f" WHERE {where}" if where else ""
    try:
        cur.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {table}({cols}){where_sql}")
        print(f"  [OK]  {name} on {table}({cols})")
    except sqlite3.IntegrityError as e:
        # Duplicates already exist — the index can't be built. Surface it so it
        # gets cleaned up, instead of silently leaving the guard off.
        print(f"  [WARN] {name}: existing duplicates block this index — {e}")

# public_id doubles as the on-disk folder name for a workspace, so a collision
# is a filesystem collision. The ORM declares unique=True, but a DB created
# before that was added may lack the index — add it defensively.
add_unique_index('uq_users_public_id',      'users',      'public_id',
                 where='public_id IS NOT NULL')
add_unique_index('uq_workspaces_public_id', 'workspaces', 'public_id',
                 where='public_id IS NOT NULL')
# One assignment per batch: the assign endpoint delete-then-inserts to enforce
# "latest assignment wins", but nothing stopped two concurrent assigns from both
# inserting. Partial index (batch_id may be NULL for batch-less assignments).
add_unique_index('uq_assignment_batch', 'assignments', 'batch_id',
                 where='batch_id IS NOT NULL')


# ── Commit ─────────────────────────────────────────────────────────────────────

conn.commit()
conn.close()
print("\n[DONE] Migration complete. You can now start the app normally.\n")
