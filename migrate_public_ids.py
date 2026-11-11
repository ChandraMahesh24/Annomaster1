"""
Migration: Add public IDs + rename workspace folders to WS-XXXXXX format.

What it does:
  1. Adds public_id column to users table (USR-XXXXXX)
  2. Adds public_id column to workspaces table (WS-XXXXXX)
  3. Assigns public IDs to all existing users
  4. Assigns public IDs to all existing workspaces
  5. Deletes orphan workspace DB records (no disk folder)
  6. Renames existing workspace folders to WS-XXXXXX format
  7. Updates folder_name in DB to match new folder

Safe to run multiple times — skips already-migrated records.

Run:  python migrate_public_ids.py
"""
import secrets
import sqlite3
import string
from pathlib import Path

DB_PATH = Path(__file__).parent / 'annomaster.db'
WS_ROOT = Path(__file__).parent / 'workspace'

if not DB_PATH.exists():
    print(f"[ERROR] Database not found at {DB_PATH}")
    raise SystemExit(1)

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row
cur = conn.cursor()


# ── ID generators ─────────────────────────────────────────────────────────────

ALPHANUM = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # no O/0, I/1


def _random_user_id():
    return 'USR-' + ''.join(secrets.choice(ALPHANUM) for _ in range(6))


def _random_ws_id():
    num = secrets.randbelow(900000) + 100000
    return f'WS-{num}'


def _all_user_ids():
    return {r['public_id'] for r in cur.execute(
        'SELECT public_id FROM users WHERE public_id IS NOT NULL').fetchall()}


def _all_ws_ids():
    return {r['public_id'] for r in cur.execute(
        'SELECT public_id FROM workspaces WHERE public_id IS NOT NULL').fetchall()}


# ── Helpers ───────────────────────────────────────────────────────────────────

def column_exists(table: str, column: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


# ── 1. Add public_id column to users ─────────────────────────────────────────

print("\n[1/6] Adding public_id column to users ...")
if column_exists('users', 'public_id'):
    print("  [SKIP] users.public_id already exists")
else:
    cur.execute("ALTER TABLE users ADD COLUMN public_id VARCHAR(20)")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_public_id ON users(public_id)")
    print("  [OK]   users.public_id added")


# ── 2. Add public_id column to workspaces ─────────────────────────────────────

print("\n[2/6] Adding public_id column to workspaces ...")
if column_exists('workspaces', 'public_id'):
    print("  [SKIP] workspaces.public_id already exists")
else:
    cur.execute("ALTER TABLE workspaces ADD COLUMN public_id VARCHAR(20)")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_workspaces_public_id ON workspaces(public_id)")
    print("  [OK]   workspaces.public_id added")

conn.commit()


# ── 3. Assign public IDs to existing users ────────────────────────────────────

print("\n[3/6] Assigning USR-XXXXXX to existing users ...")
existing_user_ids = _all_user_ids()
users = cur.execute('SELECT id, username, public_id FROM users').fetchall()
assigned = 0
for u in users:
    if u['public_id']:
        continue
    # Generate unique ID
    for _ in range(100):
        pid = _random_user_id()
        if pid not in existing_user_ids:
            break
    cur.execute('UPDATE users SET public_id = ? WHERE id = ?', (pid, u['id']))
    existing_user_ids.add(pid)
    assigned += 1
    print(f"  [ASSIGN] user {u['id']} ({u['username']}) -> {pid}")

if assigned == 0:
    print("  [SKIP] All users already have public IDs")
else:
    print(f"  [OK]   {assigned} user(s) assigned")

conn.commit()


# ── 4. Assign public IDs to existing workspaces ──────────────────────────────

print("\n[4/6] Assigning WS-XXXXXX to existing workspaces ...")
existing_ws_ids = _all_ws_ids()
workspaces = cur.execute(
    'SELECT id, name, folder_name, public_id FROM workspaces'
).fetchall()
assigned = 0
ws_id_map = {}   # id -> new public_id  (for step 6)
for ws in workspaces:
    if ws['public_id']:
        ws_id_map[ws['id']] = ws['public_id']
        continue
    for _ in range(100):
        pid = _random_ws_id()
        if pid not in existing_ws_ids:
            break
    cur.execute('UPDATE workspaces SET public_id = ? WHERE id = ?', (pid, ws['id']))
    existing_ws_ids.add(pid)
    ws_id_map[ws['id']] = pid
    assigned += 1
    print(f"  [ASSIGN] workspace {ws['id']} ({ws['name']}) -> {pid}")

if assigned == 0:
    print("  [SKIP] All workspaces already have public IDs")
else:
    print(f"  [OK]   {assigned} workspace(s) assigned")

conn.commit()


# ── 5. Delete orphan workspaces (DB record but no disk folder) ────────────────

print("\n[5/6] Cleaning orphan workspaces ...")
workspaces = cur.execute(
    'SELECT id, name, folder_name, public_id FROM workspaces'
).fetchall()
deleted = 0
for ws in workspaces:
    folder = WS_ROOT / ws['folder_name']
    if not folder.exists():
        print(f"  [DELETE] id={ws['id']} name='{ws['name']}' folder='{ws['folder_name']}' - no disk folder")
        cur.execute('DELETE FROM workspace_members WHERE workspace_id = ?', (ws['id'],))
        cur.execute('DELETE FROM workspaces WHERE id = ?', (ws['id'],))
        deleted += 1

if deleted == 0:
    print("  [SKIP] No orphan workspaces found")
else:
    print(f"  [OK]   {deleted} orphan workspace(s) deleted")

conn.commit()


# ── 6. Rename workspace folders to WS-XXXXXX format ──────────────────────────

print("\n[6/6] Renaming workspace folders ...")
workspaces = cur.execute(
    'SELECT id, name, folder_name, public_id FROM workspaces'
).fetchall()
renamed = 0
for ws in workspaces:
    old_folder = WS_ROOT / ws['folder_name']
    new_name   = ws['public_id']   # e.g. "WS-847291"

    # Already using public_id as folder name
    if ws['folder_name'] == new_name:
        print(f"  [SKIP] {ws['folder_name']}/ - already migrated")
        continue

    if not old_folder.exists():
        print(f"  [WARN] {ws['folder_name']}/ - folder not found, skipping")
        continue

    new_folder = WS_ROOT / new_name
    if new_folder.exists():
        print(f"  [ERROR] Cannot rename {ws['folder_name']}/ -> {new_name}/ - target exists!")
        continue

    # Rename on disk
    old_folder.rename(new_folder)
    # Update DB
    cur.execute(
        'UPDATE workspaces SET folder_name = ? WHERE id = ?',
        (new_name, ws['id'])
    )
    renamed += 1
    print(f"  [RENAME] {ws['folder_name']}/ -> {new_name}/ ('{ws['name']}')")

if renamed == 0:
    print("  [SKIP] No folders need renaming")
else:
    print(f"  [OK]   {renamed} folder(s) renamed")


# ── Commit & done ────────────────────────────────────────────────────────────

conn.commit()
conn.close()

print("\n" + "=" * 60)
print("[DONE] Migration complete!")
print("=" * 60)
print("\nSummary:")
print("  Users:      public_id (USR-XXXXXX) assigned")
print("  Workspaces: public_id (WS-XXXXXX) assigned")
print("  Folders:    renamed to WS-XXXXXX format")
print("  Orphans:    cleaned up")
print("\nYou can now start the app: python run.py")
