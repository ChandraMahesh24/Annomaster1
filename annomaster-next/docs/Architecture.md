# AnnoMaster-next — Architecture

## 1. Stack
| Layer | Tech |
|-------|------|
| Backend | **FastAPI**, **SQLAlchemy 2.0** (typed `mapped_column`), **Pydantic v2**, **Alembic** |
| DB | **Postgres** in prod; **SQLite** for local verification (`ALLOW_SQLITE=true`) |
| Jobs | **Celery + Redis** (ffmpeg frame extraction, YOLO predict, ZIP export); inline fallback when no broker |
| ML | **ultralytics** (YOLO), model weights in `models/` |
| Frontend | **React + Vite + TypeScript**, **@tanstack/react-query**, **react-router** |
| Media | **ffmpeg** (video → frames) on PATH |

## 2. Repository layout
```
annomaster-next/
  backend/
    app/
      api/         thin routers (parse request → call service → shape response)
      services/    business logic (no FastAPI imports beyond nothing)
      core/        paths.py (ONLY path constructor), db.py, config.py, deps.py, security.py, yolo.py
      models/      SQLAlchemy models (typed)
      schemas/     Pydantic request/response models
      workers/     Celery tasks + plain service fns (testable without a broker)
    alembic/       migrations
  frontend/
    src/
      api/         client.ts (fetch+JWT), hooks.ts, ai.ts (react-query)
      canvas/      Canvas.tsx, reducer.ts, boxes.ts, useAnnotate.ts, ClassPopup, RightPanel, SmartDetect
      routes/      Workspace.tsx (shell) + sections/ (Upload, Annotate, Dataset, Versions, Classes, Projects)
      theme/ported/ the original CSS ported verbatim, tokens aliased to semantic tokens
      react-glue.css  small React-only CSS additions
  docs/            this documentation set
  run.py           one-command launcher (backend + frontend)
  docker-compose.yml
```

## 3. The router/service split (mirrors the original api/ vs core/)
- **Routers** (`api/`) parse the request, enforce roles, and delegate. They may
  import `Request`/`Response`/`Session`.
- **Services** (`services/`) hold the logic and are unit-testable without HTTP.
- **`core/paths.py` is the ONLY place that constructs filesystem paths.**

## 4. Two sources of truth (deliberate)
- **Database** holds: users, workspaces, membership, `images` (metadata only),
  `upload_batches`, `assignments`, annotation `locks`, `audit_log`.
- **Filesystem** holds all image + annotation **data**, in a load-bearing layout:
  ```
  workspace/<WS-XXXXXX>/projects/<project>/
    Active_Work/job_<DATETIME>/{images,labels}/
    Completed_Datasets/...          (legacy; port keeps files in place)
    Versions/<name>/                immutable snapshot + data.yaml
    project.json  _uploads.json  versions.json
  ```
- **Files never move.** Lifecycle (`active → in_dataset`, `split`) is a **DB
  column change**. A label's path is derived from its image path by swapping
  `images/` → `labels/`.

## 5. Annotation storage (what makes exports safe)
```
labels/<name>.txt                 CONFIRMED boxes only  → ground truth
labels/<name>.suggestions.json    suggested + rejected + confidence (sidecar)
```
- `Image.is_annotated` can't flip on detections alone.
- Rejected boxes survive reload (a re-run won't re-suggest them).
- Versions/exports copy labels by explicit `<stem>.txt`, never by globbing, so the
  sidecar can't leak into a dataset.

## 6. Data model (key tables)
- `users` — `id`, `public_id` (USR-…), email, password hash, login lockout.
- `workspaces` — `id`, `public_id`/`folder_name` (WS-…).
- `workspace_members` — (workspace, user, role) unique; CASCADE.
- `images` — `workspace_id`, `project`, `batch_id`, `rel_path`, `md5`,
  `status` (`active|in_dataset`), `split` (`train|valid|test`), `is_annotated`,
  `is_null`, provenance (`uploaded/annotated/reviewed_by/at`, `added_to_dataset_at`).
- `upload_batches` — one row per bulk upload; `source` (`images|folder|zip|video`).
- `assignments` — one live per batch (partial unique on `batch_id`);
  `total_images`/`done_images`, `status`.
- Enums are DB `CHECK` constraints; `workspace_id` is a real FK `ON DELETE CASCADE`
  on every scoped table (fixes the original's orphan-row problem).

## 7. Auth & isolation
- `core/security.py::extract_token` reads `Authorization: Bearer`, the `token`
  cookie, **or** `?token=` (for `<img>`).
- `workspace_role(*roles)` dependency = the isolation primitive: resolves the
  member, checks role, and scopes the query to that workspace.

## 8. Frontend architecture
- **`Workspace.tsx`** is the shell (header with brand/project/progress/nav/save,
  left nav rail, status bar). It owns the shared `useAnnotate` state and a
  **batch filter** (clicking a batch card opens the annotator on that batch).
- **`useAnnotate`** owns image list (paginated + filtered + batch-scoped), current
  index, the canvas reducer, and **auto-save** (flush-on-nav + debounce + flush-on-
  unmount).
- **`canvas/reducer.ts`** is a state machine: `idle → drawing/moving/resizing →
  idle`. Draw commits to idle (never "selected"); editing a suggestion = accept.
- **`canvas/boxes.ts`** holds the `Boxes` rules: states, IoU, the two reconcilers
  (`reconcile` for Review, `reconcileAutoSave` for Auto-approve), serialise.
- **`Canvas.tsx`** paints via 2D context, persists a zoom/pan `view`, and reports
  it up (`onView`) so the class popup can be placed on the canvas.
- React Query keys are structured so a mutation invalidates exactly what changed
  (`['batches', wid, project]`, `['dataset', …]`, `['ai-models']`, …).

## 9. Background jobs
Each job has a plain **service function** (real work, testable) + a thin **Celery
wrapper**. The endpoint runs it inline when Redis is unreachable, or enqueues it
when the broker is up — same code path. `redis_ping()` decides.

## 10. Verification model (this machine)
No Docker/Postgres/Redis. Set `DATABASE_URL=sqlite:///…` + `WORKSPACE_ROOT=…`,
`alembic upgrade head`, then drive a `TestClient` script that writes results to a
file (never through a pipe — see [memory.md](memory.md)). ffmpeg + ultralytics are
real, so video extraction and YOLO predict are verified for real.
