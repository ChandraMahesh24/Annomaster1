"""
DB ↔ filesystem ↔ index consistency checker.

WHY THIS EXISTS
───────────────
AnnoMaster keeps the same facts in THREE places that can silently disagree:

  1. central `annomaster.db` → `images` table      (metadata: who/when/status)
  2. per-project `.media_index.db` → `media` table (the fast index the UI reads)
  3. the filesystem                                (the actual image + .txt files)

Nothing keeps them in lockstep: every central-DB write in the upload/annotate
paths is wrapped in `try/except: pass`, so a failed insert leaves the file on
disk with no row and no error. This script surfaces that drift in BOTH
directions, per workspace, using `app.core.paths` to build every path (never a
hand-built string), so it stays correct if the on-disk layout ever changes.

It is READ-ONLY. It changes nothing; it reports. Run it before a backup, after
a crash, or on a schedule.

USAGE
─────
    python scripts/check_consistency.py                 # all workspaces
    python scripts/check_consistency.py --workspace 7   # one workspace (by id)
    python scripts/check_consistency.py --json          # machine-readable

Exit code is 0 when clean, 1 when any drift is found — so it can gate a backup
or a deploy in a shell script.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

# Import the app only to reuse its path builder and config — never to hand-build
# a workspace/project path here, which is exactly the rule paths.py enforces.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ALLOWED_IMG = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp'}


def _load_app():
    # Windows consoles default to cp1252; force UTF-8 so report glyphs render.
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    from app import create_app
    return create_app()


def _iter_image_dirs(project_root):
    """
    Yield every (label, images_dir, labels_dir) under a project that is
    supposed to hold annotatable images: Active_Work jobs and the three
    Completed_Datasets splits. Mirrors the layout documented in paths.py.
    """
    aw = project_root / 'Active_Work'
    if aw.exists():
        for job in sorted(p for p in aw.iterdir() if p.is_dir()):
            yield (f'Active_Work/{job.name}', job / 'images', job / 'labels')
    cd = project_root / 'Completed_Datasets'
    if cd.exists():
        for job in sorted(p for p in cd.iterdir() if p.is_dir()):
            for split in ('train', 'valid', 'test'):
                sp = job / split
                if sp.exists():
                    yield (f'Completed_Datasets/{job.name}/{split}',
                           sp / 'images', sp / 'labels')


def check_workspace(app, ws_row):
    """Return a findings dict for one workspace. Pure measurement, no writes."""
    from app.core.paths import project_dir, workspace_dir

    wid, folder = ws_row.id, ws_row.folder_name
    out = {
        'workspace_id': wid, 'folder': folder,
        'folder_missing': False,
        'db_rows_missing_file': [],       # central images row → no file on disk
        'files_missing_db_row': [],       # file on disk → no central images row
        'files_missing_index_row': [],    # file on disk → no .media_index.db row
        'orphan_suggestion_sidecars': [], # .suggestions.json with no .txt sibling image
        'labels_missing_image': [],       # .txt with no matching image
    }

    # paths.py reads current_app.config, so everything runs inside a context.
    with app.app_context():
        from app.models.image import Image

        wd = workspace_dir(folder)
        if not wd.exists():
            out['folder_missing'] = True
            return out

        proj_root = wd / 'projects'
        if not proj_root.exists():
            return out

        for proj in sorted(p for p in proj_root.iterdir() if p.is_dir()):
            project = proj.name
            pdir = project_dir(folder, project)

            # ── Central images table for this project ──
            db_paths = {
                r.rel_path for r in Image.query.filter_by(
                    workspace_id=wid, project=project).all()
            }

            # ── Per-project media index for this project ──
            index_paths = set()
            idx_db = pdir / '.media_index.db'
            if idx_db.exists():
                try:
                    ic = sqlite3.connect(str(idx_db))
                    index_paths = {r[0] for r in ic.execute('SELECT path FROM media')}
                    ic.close()
                except sqlite3.Error:
                    pass

            # ── Walk the filesystem ──
            disk_rel_paths = set()
            for _label, img_dir, lbl_dir in _iter_image_dirs(pdir):
                if img_dir.exists():
                    img_stems = set()
                    for f in img_dir.iterdir():
                        if f.suffix.lower() not in ALLOWED_IMG:
                            continue
                        rel = str(f.relative_to(pdir)).replace('\\', '/')
                        disk_rel_paths.add(rel)
                        img_stems.add(f.stem)
                        # File on disk with no central DB row?
                        # (only meaningful for Active_Work — Completed rows may
                        #  have been intentionally removed from the index)
                        norm = rel.replace('/', '\\')  # central table may store either sep
                        if rel not in db_paths and norm not in db_paths:
                            out['files_missing_db_row'].append(f'{project}:{rel}')
                        if rel not in index_paths and norm not in index_paths:
                            out['files_missing_index_row'].append(f'{project}:{rel}')

                # ── Labels + suggestion sidecars ──
                if lbl_dir.exists():
                    for lf in lbl_dir.iterdir():
                        if lf.suffix == '.txt' and lf.stem not in img_stems:
                            out['labels_missing_image'].append(f'{project}:{lf.name}')
                        # sidecar: <stem>.suggestions.json must have a <stem>.txt
                        if lf.name.endswith('.suggestions.json'):
                            stem = lf.name[:-len('.suggestions.json')]
                            if not (lbl_dir / f'{stem}.txt').exists():
                                out['orphan_suggestion_sidecars'].append(
                                    f'{project}:{lf.name}')

            # ── Central rows pointing at files that no longer exist ──
            for rp in db_paths:
                candidate = pdir / rp.replace('\\', '/')
                if not candidate.exists():
                    out['db_rows_missing_file'].append(f'{project}:{rp}')

    return out


def find_orphan_rows(app):
    """
    DB rows whose workspace_id references a workspace that no longer exists.
    `workspace_id` is a plain integer (not a foreign key) on images /
    upload_batches / assignments / annotation_locks, so a deleted workspace
    strands every one of its metadata rows — nothing cleans them up.
    """
    with app.app_context():
        from app import db
        from sqlalchemy import text
        live = {r[0] for r in db.session.execute(text('SELECT id FROM workspaces'))}
        result = {}
        for table in ('images', 'upload_batches', 'assignments', 'annotation_locks'):
            rows = db.session.execute(
                text(f'SELECT workspace_id, COUNT(*) c FROM {table} GROUP BY workspace_id')
            ).fetchall()
            orphaned = {r[0]: r[1] for r in rows if r[0] not in live}
            if orphaned:
                result[table] = orphaned
        return result


def main():
    ap = argparse.ArgumentParser(description='DB↔filesystem consistency check')
    ap.add_argument('--workspace', type=int, help='check only this workspace id')
    ap.add_argument('--json', action='store_true', help='machine-readable output')
    args = ap.parse_args()

    app = _load_app()
    with app.app_context():
        from app import db
        from sqlalchemy import text
        q = 'SELECT id, folder_name FROM workspaces'
        if args.workspace:
            q += f' WHERE id = {int(args.workspace)}'
        ws_rows = [type('R', (), {'id': r[0], 'folder_name': r[1]})()
                   for r in db.session.execute(text(q))]

    per_ws = [check_workspace(app, w) for w in ws_rows]
    orphans = find_orphan_rows(app)

    report = {'workspaces': per_ws, 'orphan_rows': orphans}

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_human(report)

    # Non-zero exit if any drift found — lets a shell script gate on it.
    drift = bool(orphans) or any(
        w['folder_missing'] or w['db_rows_missing_file'] or w['files_missing_db_row']
        or w['files_missing_index_row'] or w['orphan_suggestion_sidecars']
        or w['labels_missing_image']
        for w in per_ws
    )
    sys.exit(1 if drift else 0)


def _print_human(report):
    def head(s): print(f'\n{"─" * 66}\n{s}\n{"─" * 66}')

    head('ORPHAN ROWS (workspace_id points at a deleted workspace)')
    if not report['orphan_rows']:
        print('  none')
    else:
        for table, orphaned in report['orphan_rows'].items():
            for wid, n in orphaned.items():
                print(f'  {table:18} workspace_id={wid}: {n} stranded row(s)')

    for w in report['workspaces']:
        head(f"WORKSPACE {w['workspace_id']}  ({w['folder']})")
        if w['folder_missing']:
            print('  [!] DB row exists but the workspace folder is MISSING on disk')
            continue
        rows = [
            ('DB rows → missing file',        w['db_rows_missing_file']),
            ('files → no central DB row',     w['files_missing_db_row']),
            ('files → no media-index row',     w['files_missing_index_row']),
            ('orphan suggestion sidecars',     w['orphan_suggestion_sidecars']),
            ('labels → no matching image',     w['labels_missing_image']),
        ]
        clean = True
        for label, items in rows:
            if items:
                clean = False
                print(f'  {label:30} {len(items)}')
                for x in items[:5]:
                    print(f'      {x}')
                if len(items) > 5:
                    print(f'      … and {len(items) - 5} more')
        if clean:
            print('  [ok] consistent')


if __name__ == '__main__':
    main()
