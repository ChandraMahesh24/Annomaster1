# Testing and maintenance reference

## Which application to work on

Before changing code, read [PROJECT_AUDIT_AND_PROGRESS.md](../PROJECT_AUDIT_AND_PROGRESS.md)
completely. It supersedes the dated review's test totals and tracks the broader audit.

The repository root is the live Flask + SQLite + vanilla JavaScript application. `annomaster-next/` is a separate FastAPI/React port. Read `CLAUDE.md` before changes; read `PORT_PLAN.md` before port work. See [architecture](architecture.md) and [installation](installation.md) for the existing detailed guides.

## Repeatable checks

From the repository root, using the Python environment where the application dependencies from `requirements.txt` are installed:

```powershell
python -m unittest discover -s tests -v
```

No pytest dependency is needed. The suite creates temporary users, membership, files and an in-memory database, disables rate limiting, and closes project index connections before cleaning up (required on Windows). It does not launch `run.py` or connect to the live database. The configuration inherits the normal Config but overrides database, workspace and signing secrets. Model files are not loaded by these checks.

The four defects in the [dated review report](code-review-2026-11-13.md) are fixed. The expanded suite runs 41 tests: 40 pass and the symlink-escape test is skipped on this Windows account because symlink creation requires privileges. There are no expected failures. Coverage includes invalid-save preservation, path variants, null lock conflicts, JSON validation, auth and team API workflows, deletion cleanup, version failure safety, selected-dataset export, retained duplicate indexing, and a real PNG upload-to-version ZIP flow. Selected real Chrome workflows, local YOLO11n/SAM3 inference, and MP4 extraction are now verified separately; exhaustive control coverage is still incomplete.

`python scripts/run_audit_tests.py` runs the same tests and refreshes `docs/audit-test-results.json`.
`python scripts/audit_inventory.py` regenerates the static route/control ledger without importing the application.
`node scripts/test_annotation_lifecycle.cjs` runs nine pure state tests against the live `Boxes` module. This requires Node; it does not exercise a browser canvas.

Install audit-only dependencies with `python -m pip install --target .audit-tools -r scripts/audit-requirements.txt`. Run `python scripts/browser_audit.py PHASE`, where PHASE is `probe`, `auth`, `dashboard`, `settings`, `project`, `members`, `ai`, or `media`. Run phases sequentially. Each starts its own disposable server on port 5055, refuses an occupied port, uses installed Chrome, then stops its own server. Never stop the user's server or test against production data. The sandbox may require execution approval for localhost/browser access. Chrome path is currently Windows-specific. AI requires locally available weights/CUDA; missing prerequisites must be BLOCKED, not PASS. The media phase uses workspace-local imageio-ffmpeg without modifying system PATH.

Raw screenshots, temporary downloads, fixtures and response logs are in ignored `.audit-browser/`. Run `python scripts/summarize_browser_audit.py` to preserve phase results and console/network events in [audit-browser-results.json](audit-browser-results.json), excluding credential/token fixtures. PASS applies to the named check only; OBSERVED is an inventory entry. Expected 401/404/409/422 responses are deliberate validation tests; navigation-aborted requests are retained for review. Native color-picker dialogs, all permission states and all advanced canvas controls are not yet covered. See the permanent progress file before continuing.

Input contracts: user-supplied file paths must be relative, contain no traversal and resolve inside the project. Keep both image and derived label/sidecar destinations contained. Annotation writes validate the complete list before modifying labels: invalid payloads receive HTTP 400, while direct `write_yolo_label` calls raise `ValueError`. Width and height must be within (0, 1] and remain positive after six-decimal serialization. Auth JSON must be an object and supplied text fields must be strings (optional null values retain existing empty-value behavior).

For a dependency-free Python syntax check without importing the app or writing bytecode:

```powershell
python -c "import ast; from pathlib import Path; files=list(Path('app').rglob('*.py'))+[Path('config.py'),Path('run.py')]+list(Path('scripts').glob('*.py')); [ast.parse(p.read_text(encoding='utf-8-sig'),filename=str(p)) for p in files]; print('Syntax OK:',len(files),'Python files')"
```

When Node is installed, check ordinary script syntax with `node --check <file>`. Treat ES modules such as `auth-scene.js` as modules; a syntax check does not verify browser behavior. Exercise the annotation canvas in a browser after frontend changes.

## Code map and invariants

| Area | Reference | Rule |
|---|---|---|
| App setup, page routes, health | `app/__init__.py` | App factory creates tables; use a test configuration for automated tests |
| Authentication and roles | `app/utils/security.py`, `app/api/auth.py` | API handlers require login and appropriate workspace membership |
| Filesystem layout | `app/core/paths.py` | Keep path construction centralized; enforce containment for untrusted paths |
| Annotation persistence | `app/api/annotations.py`, `app/core/yolo.py` | Confirmed boxes in YOLO `.txt`; never put pending suggestions into ground truth |
| Suggestions | `app/core/suggestions.py` | Suggested/rejected boxes persist in a separate JSON sidecar |
| Edit locks | `app/api/locks.py` | Every annotation mutation must respect another user's live lock |
| Media index | `app/core/db_index.py` | Derived per-project index; close handles before directory removal/rename on Windows |
| Canvas state | `static/js/main.js`, `Boxes` module | Human edits accept suggestions; re-runs reconcile against persisted state |
| Prompt annotation | `static/js/features/prompt-annotate.js`, `app/core/prompt_models.py` | Use the existing suggestion lifecycle |
| Theme | `static/css/tokens.css`, `static/js/theme.js` | Use semantic tokens and preserve stylesheet cascade order |

`static/js/engine/canvas.js` is a stale reference copy according to `CLAUDE.md`; confirm what templates load before editing frontend files. Database and filesystem are separate sources of truth, so backing up only SQLite does not preserve annotations.

## Before and after a change

1. Read the relevant code and documentation; check `git status --short` for existing changes.
2. Use temporary database and workspace paths for tests. Do not run the default app factory as a supposedly read-only database audit: it calls `db.create_all()`.
3. Run the isolated suite. Add focused coverage for changed persistence, permission or cross-user behavior.
4. For annotation changes, manually check draw/edit, accept/reject, save/reload, null images and lock conflicts. Verify exported labels and sidecar exclusion on a disposable project.
5. For upload/export changes, test image, video, ZIP, train/valid/test split and version download workflows using disposable data.
6. Update the relevant guide and record any checks that could not run.

## Operational references

Read `scripts/backup.py` before using it to snapshot SQLite and the workspace together. Read `scripts/check_consistency.py` before checking database/filesystem/index drift. Their live-data commands were not executed during this review.

Schema updates use hand-written migration scripts (`migrate_db.py` and related scripts); the root app has no Alembic migration history directory. Back up first and validate on a copy. Do not assume `flask db upgrade` upgrades this application.

For production, configure strong `SECRET_KEY` and `JWT_SECRET`, public reset-link URL and mail delivery; use a production WSGI server. The development launcher has debug enabled. Check installed `PyJWT` exposes `jwt.encode` if login fails; the unrelated `jwt` distribution uses the same import name.
