"""
Backup — captures BOTH sources of truth together.

WHY BOTH, ALWAYS
────────────────
A backup of the database alone restores metadata that points at images which
are not there. A backup of the filesystem alone restores images and labels
with no users, workspaces, memberships, locks or audit history. Either one on
its own leaves the app in exactly the DB↔filesystem drift state this whole
audit is about. So this script refuses to do one without the other.

WHAT IT CAPTURES
────────────────
  1. annomaster.db          via the SQLite Online Backup API — a CONSISTENT
                            snapshot taken while the app keeps running. A raw
                            file copy is unsafe under journal_mode=WAL: the
                            committed data lives across the .db, .db-wal and
                            .db-shm files, and a plain copy can catch them
                            mid-checkpoint and restore a torn database.
  2. every per-project      copied the same way — each `.media_index.db` is a
     .media_index.db        live WAL database too.
  3. workspace/             the image + label + sidecar tree, copied wholesale.

Layout produced:
    <out>/backup_<UTC-timestamp>/
        annomaster.db
        MANIFEST.json          # counts + integrity_check result + timestamp
        workspace/...          # full tree, incl. per-project index DBs

USAGE
─────
    python scripts/backup.py                 # → ./backups/backup_<ts>/
    python scripts/backup.py --out D:/backups
    python scripts/backup.py --quick         # DB only, skip the file tree
                                             #   (explicitly unsupported to
                                             #    restore from — see RESTORE)

RESTORE  (read before you need it)
──────────────────────────────────
Restoring is a whole-directory swap, and you MUST restore both halves from the
SAME backup or you reintroduce drift:

  1. Stop the app (no writers).
  2. Move the current annomaster.db, annomaster.db-wal, annomaster.db-shm and
     the workspace/ tree aside (do not delete until the restore is verified).
  3. Copy annomaster.db and workspace/ from the backup directory into place.
     There is no -wal/-shm to restore: the snapshot is already checkpointed
     into the single .db file.
  4. Run:  python scripts/check_consistency.py
     A restore is only complete when this reports no NEW drift versus the
     MANIFEST captured at backup time.
  5. Start the app; hit /health; it must return 200.

Restoring DB-only or files-only is NOT supported and will leave the app
broken — the consistency check in step 4 is what catches an accidental
half-restore.
"""
import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Windows consoles default to cp1252 and choke on non-ASCII; force UTF-8.
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent


def _long(p: Path) -> str:
    """
    Windows caps paths at 260 chars (MAX_PATH). The workspace tree is deep
    (workspace/<WS>/projects/<proj>/Active_Work/job_<ts>/images/<long-name>)
    and real filenames here are long, so a backup to any non-trivial root can
    blow past it. The `\\?\` prefix opts a specific call out of MAX_PATH.
    No-op on non-Windows.
    """
    if sys.platform == 'win32':
        ap = str(p.resolve())
        if not ap.startswith('\\\\?\\'):
            return '\\\\?\\' + ap
        return ap
    return str(p)


def _snapshot_sqlite(src: Path, dst: Path) -> dict:
    """
    Consistent copy of a live SQLite DB via the Online Backup API, then a
    quick integrity_check on the copy so a corrupt source is caught now, not
    at restore time.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    src_conn = sqlite3.connect(_long(src))
    dst_conn = sqlite3.connect(_long(dst))
    try:
        src_conn.backup(dst_conn)          # atomic, consistent, WAL-safe
        integrity = dst_conn.execute('PRAGMA integrity_check').fetchone()[0]
    finally:
        dst_conn.close()
        src_conn.close()
    return {'source': str(src), 'integrity_check': integrity}


def _count_tables(db_file: Path) -> dict:
    conn = sqlite3.connect(str(db_file))
    try:
        counts = {}
        for t in ('users', 'workspaces', 'workspace_members', 'images',
                  'upload_batches', 'assignments', 'annotation_locks', 'audit_log'):
            try:
                counts[t] = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
            except sqlite3.Error:
                counts[t] = None
        return counts
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description='Backup annomaster (DB + filesystem)')
    ap.add_argument('--out', default=str(ROOT / 'backups'),
                    help='destination root (default ./backups)')
    ap.add_argument('--quick', action='store_true',
                    help='DB only — NOT restorable on its own; see module docstring')
    args = ap.parse_args()

    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    dest = Path(args.out) / f'backup_{ts}'
    dest.mkdir(parents=True, exist_ok=True)

    main_db = ROOT / 'annomaster.db'
    if not main_db.exists():
        print(f'[ERROR] {main_db} not found — nothing to back up.')
        sys.exit(1)

    manifest = {
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'quick': args.quick,
        'main_db': None,
        'index_dbs': [],
        'table_counts': None,
        'workspace_tree_copied': False,
    }

    print(f'[1] snapshotting annomaster.db → {dest / "annomaster.db"}')
    manifest['main_db'] = _snapshot_sqlite(main_db, dest / 'annomaster.db')
    manifest['table_counts'] = _count_tables(dest / 'annomaster.db')
    print(f'    integrity_check: {manifest["main_db"]["integrity_check"]}')

    if args.quick:
        print('[2] --quick: skipping workspace/ tree (DB-only backup is NOT restorable alone)')
    else:
        ws_root = ROOT / 'workspace'
        if ws_root.exists():
            print(f'[2] snapshotting per-project index DBs (WAL-safe)…')
            # Copy each .media_index.db via the backup API rather than letting
            # copytree grab it mid-WAL-checkpoint.
            index_dbs = list(ws_root.rglob('.media_index.db'))
            for idx in index_dbs:
                rel = idx.relative_to(ROOT)
                info = _snapshot_sqlite(idx, dest / rel)
                manifest['index_dbs'].append(
                    {'path': str(rel), 'integrity_check': info['integrity_check']})
            print(f'    {len(index_dbs)} index DB(s) snapshotted')

            print(f'[3] copying workspace/ tree (images, labels, sidecars, json)…')
            shutil.copytree(
                _long(ws_root), _long(dest / 'workspace'),
                # index DBs already snapshotted consistently above; skip the
                # live ones so copytree doesn't overwrite them with a torn copy.
                ignore=shutil.ignore_patterns(
                    '.media_index.db', '.media_index.db-wal', '.media_index.db-shm'),
                dirs_exist_ok=True,
            )
            manifest['workspace_tree_copied'] = True
            print('    done')
        else:
            print('[2] no workspace/ directory found — skipping file tree')

    (dest / 'MANIFEST.json').write_text(
        json.dumps(manifest, indent=2), encoding='utf-8')

    print(f'\n[DONE] backup at: {dest}')
    if manifest['main_db']['integrity_check'] != 'ok':
        print('[WARN] integrity_check was NOT ok — investigate before trusting this backup.')
        sys.exit(2)


if __name__ == '__main__':
    main()
