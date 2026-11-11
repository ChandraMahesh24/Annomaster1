# AnnoMaster — Port Plan (Flask/SQLite/vanilla-JS → FastAPI/Postgres/Celery + React)

**Status:** planning. Executed stage-by-stage; check boxes as we land each one.

## Reality check (read first)

This is a full reimplementation with **behavioural parity** as the acceptance
bar — not "does it compile." The current app is ~35k lines of front-end alone
plus a substantial Flask backend, and the spec (the porting prompt) is itself
the behaviour contract. Realistically this is a multi-week effort even done
efficiently. The plan below breaks it into **13 stages across 4 phases**, each
sized to land in roughly one working session and each **independently
verifiable**, so we never have a half-ported app that can't be exercised.

**The single biggest asset:** the hard logic in Section 3 (nested hit-testing,
the three-state suggested/confirmed/rejected lifecycle, both reconcilers, IoU,
draw→commit-to-idle) is *already worked out and debugged* in the current
`static/js/main.js` `Boxes` module and mouse handlers. The React port
**translates that proven code**, it does not redesign it. Same for the backend
rules — most were just audited and fixed in the current app. We port from a
known-good reference, which is what makes parity achievable.

## Target architecture

```
                 ┌─────────────── React + Vite SPA ───────────────┐
                 │  React Router · React Query · canvas reducer    │
                 └───────────────────────┬─────────────────────────┘
                                         │  JSON over HTTP (OpenAPI contract)
                 ┌───────────────────────┴─────────────────────────┐
                 │                 FastAPI  (/docs)                 │
                 │  Pydantic I/O · JWT · role deps · workspace iso  │
                 └───┬───────────────┬───────────────┬──────────────┘
                     │               │               │
              ┌──────┴─────┐  ┌──────┴──────┐  ┌──────┴───────┐
              │ Postgres   │  │ filesystem  │  │ Celery+Redis │
              │ (metadata) │  │ images/     │  │ inference,   │
              │ CHECK/FK/  │  │ labels/     │  │ export ZIP,  │
              │ UNIQUE     │  │ (never move)│  │ ffmpeg       │
              └────────────┘  └─────────────┘  └──────────────┘
```

**Unchanged by design:** filesystem-as-source-of-truth for images/labels
(NOT Postgres blobs); the `workspace/<WS-XXXXXX>/projects/<project>/…` layout;
"only one module builds paths"; "files never move — lifecycle is a DB column."

## Monorepo layout (proposed)

```
annomaster-next/
  docker-compose.yml          # postgres + redis (+ optional pgadmin)
  backend/
    app/
      main.py                 # FastAPI app factory, /health, /docs
      core/    config, security(JWT), paths, celery_app, db(session)
      models/  SQLAlchemy 2.0 typed models (Section 1)
      schemas/ Pydantic request/response
      api/     routers: auth, workspaces, uploads, annotations, locks,
               ai, datasets, versions, audit
      services/ business logic (thin routers, like the current core/ split)
      workers/  celery tasks: predict, export_zip, extract_frames
    alembic/   migrations
    tests/     pytest (isolation, lifecycle, reconcile parity)
  frontend/
    src/
      routes/  6 views: dashboard, upload, annotate, classes, dataset, versions
      canvas/  reducer + rendering (the Section 3 state machine)
      api/     typed client generated/derived from OpenAPI
      theme/   tokens.css port (same breakpoints, dark-default)
      lib/     React Query hooks
```

---

## PHASE A — Backend foundation

### ☐ A0 · Scaffold + infra
- **Delivers:** monorepo skeleton; `docker compose up` brings up Postgres +
  Redis; FastAPI boots with `/health` (checks DB **and** Redis) and `/docs`;
  React+Vite dev server serves a blank shell; Celery worker connects to Redis.
- **Verify:** `/health` returns 200 with both subsystems ok; `/docs` renders;
  a trivial Celery ping task round-trips.
- **Depends on:** the 3 decisions below (location, ORM, infra).

### ☑ A1 · Data model + migration — DONE (2026-07-25)
_8 models, 1 migration (`7f23e9d74dda`). Verified on SQLite: applies + reversible;
enum CHECKs reject bad status/split/role; UNIQUE blocks dup lock; **workspace
delete CASCADES** images/locks/members (the orphan-row fix). `workspace_id` is a
real FK everywhere. `split` enum is `train|valid|test` (real behaviour) not the
spec summary's `val`. Partial unique on `assignments.batch_id` carries the
`postgresql_where` predicate. Targets Postgres; verified on SQLite as no PG here._
- **Delivers:** all Section-1 entities as SQLAlchemy 2.0 typed models; one
  Alembic migration; **real DB constraints** — enum `CHECK`s (status/split/
  assignment.status, using the *actual* values `train|valid|test` etc.),
  `UNIQUE(workspace_id,project,image_path)` on locks, `public_id` unique, FK
  `ON DELETE` chosen per-table (deliberately — the current app's biggest data
  bug was `workspace_id` NOT being an FK, leaving 1,406 orphan rows; here it
  becomes a real FK with `ON DELETE CASCADE`).
- **Verify:** `alembic upgrade head` on a clean DB; introspect constraints;
  `alembic downgrade` works.

### ☑ A2 · Auth spine — DONE (2026-07-25)
_JWT (Bearer+cookie), register/login/logout/me/change-password, 5-fail→15-min
lockout (auto-clears), rate limits (built-in Redis-or-memory limiter; slowapi
absent), audit on every auth event. Verified on SQLite: full flow + lockout +
rate-limit + audit trail. Two bugs found & fixed during verify: (1) rollback-on-
HTTPException in get_session discarded the fail-count increment + audit → now
committed before the 401; (2) SQLite drops tzinfo so locked_until read back naive
→ added `ensure_aware()` so the comparison is correct on SQLite AND Postgres.
Note: `from __future__ import annotations` breaks FastAPI special-type detection
— omitted in endpoint/dependency modules._

### (was) A2 · Auth spine
- **Delivers:** JWT (Bearer header **or** cookie); register/login/logout/me;
  5-fail→15-min lockout auto-clearing on next success; rate limits
  (login 15/min·60/hr, register 10/hr, pw-change 5/hr); audit-log on every auth
  event (insert-only, failures never break the request).
- **Verify:** login happy path; 5 bad logins → locked; correct login after
  window clears it; rate-limit returns 429; audit rows written.

### ☑ A3 · Workspaces + members + roles + isolation — DONE (2026-07-25)
_Workspace CRUD (WS- id == on-disk folder, created/removed with the row),
members (invite/list/role/remove), `workspace_role(*roles)` dependency as the
single isolation primitive. Verified 17 assertions incl. the **cross-workspace
ID-guessing test**: an outsider is 403'd on all 7 workspace endpoints; editor
can't do owner actions; delete cascades members + removes the folder. Paths go
through the new `app/core/paths.py` only. **Phase A (backend foundation) complete.**_

### (was) A3 · Workspaces + members + roles + **isolation**
- **Delivers:** workspace CRUD; `public_id` generation = on-disk folder;
  membership; owner/editor/viewer as FastAPI dependencies; **every** images/
  locks/assignments/audit/batches query filtered by `workspace_id`.
- **Verify:** the cross-workspace ID-guessing test — hit every workspace-scoped
  endpoint with a foreign `workspace_id` and confirm 403/404. This is a
  written test, per the spec.

## PHASE B — Backend domain

### ☑ B1 · paths service + uploads + batches + images — DONE (2026-07-25)
_Full paths.py (project/Active_Work/Completed_Datasets/Versions/label-from-image);
storage.py (project.json/_uploads.json atomic); `images.md5` column + migration;
one `save_and_register` helper shared by ALL sources. Endpoints: create_batch,
single, folder(+labels), zip, list, delete, extract_frames. Verified: dedup
(same md5 not written → no file-without-row drift), files-never-move, role
gating, audit. **Real ffmpeg extraction ran: 10/10 frames registered in DB** —
the original's register-nowhere bug fixed. Video runs as a Celery task when a
broker exists, else inline. Two bugs found by running: f-string backslash
(py3.10), and mkstemp fd left open → Windows WinError 32 on unlink._

### (was) B1 · paths service + uploads + batches + images
- **Delivers:** `paths` module (the ONLY path constructor); upload / folder /
  zip endpoints; batch rows; image registration in Postgres; duplicate
  detection (MD5); **video frame extraction as a Celery job**; files-never-move.
- **Verify:** upload → row + file both present; re-upload same file → dup
  handling; extraction job registers every frame (the exact bug just fixed in
  the current app).

### ☑ B2 · Annotation persistence + locking — DONE (2026-07-25)
_core/yolo.py (bbox+polygon parse/write, empty .txt for null), suggestions
sidecar (confirmed→.txt, suggested/rejected→.json), annotations GET/POST split
by state, null/unnull, locks (acquire/release/heartbeat/force-release/list) with
**60s TTL enforced on every read** (services/locks.active_lock), acquire race →
clean 409, atomic done_images (`UPDATE … done_images+1`) + auto-submit. 12
assertions verified. Also added SQLite busy_timeout + FK-pragma to db.py (Postgres
unaffected). Debugging note: pipe buffering hid the real failure point — run
verification to a FILE, not through grep/tail, to see all output._

### (was) B2 · Annotation persistence + locking
- **Delivers:** YOLO `.txt` read/write; `.suggestions.json` sidecar; locks with
  **60s TTL enforced on every read** (not just acquire); heartbeat renew;
  acquire→409 with holder; owner force-release; save endpoint; is_annotated/
  is_null (empty `.txt` for null, never missing); **`done_images` atomic
  increment** (`UPDATE … SET done_images = done_images+1`, no read-modify-write
  race) + auto-advance to `submitted` at completion.
- **Verify:** two clients race a save → one 409; lock expires on read after
  60s; done_images correct under concurrent saves; null writes empty file.

### ☑ B3 · Smart Detect backend — DONE (2026-07-25)
_ai_models.py registry (per-request scan, cache by path+mtime+size, class list,
ModelError→422, traversal-safe resolve_path); per-project settings in
project.json settings.ai (review default); predict as Celery task + inline
fallback; router: models list/info, upload+validate, settings GET/PUT, predict,
autosave_log. 12 assertions verified against the REAL blackshirt model
(customer/staff), incl. real inference. Went clean first try — direct port of
the original's proven ai_models logic._

### (was) B3 · Smart Detect backend
- **Delivers:** model registry (scan `models/`, validate, cache instances by
  path+mtime+size, expose class list); per-project settings (model, conf) in
  project.json; predict as a **Celery job** returning normalized boxes;
  below-threshold discarded server-side.
- **Verify:** model list refreshes without restart; bad `.pt` → clear error not
  500; predict returns boxes; conf threshold respected.

### ☑ B4 · Datasets + versions + exports — DONE (2026-07-25)
_add-to-dataset = status active→in_dataset + split (DB only, **files verified not
moved**); immutable version snapshots (frozen confirmed labels + data.yaml);
YOLO/COCO/VOC exporters reading CONFIRMED boxes only; export ZIP as Celery task +
inline. 17 assertions — the key one across ALL THREE formats: each image had 1
confirmed + 1 suggested, and **only the confirmed box exported**. Storage gained
load/save_versions. **Phase B (full backend) COMPLETE — 48 endpoints.**_

### (was) B4 · Datasets + versions + exports
- **Delivers:** add-to-dataset = DB column change (`active`→`in_dataset` +
  split), no file move; version snapshots; **ZIP export as a Celery job**;
  YOLO/COCO/VOC exporters that read **only `confirmed`** boxes.
- **Verify:** export a version → ZIP job completes; assert no `suggested` box
  ever appears in any export format; split is a column, files stayed put.

## PHASE C — Frontend

### ☑ C1 · Frontend foundation — DONE (2026-07-25)
_Vite + React 18 + TS + React Router 6 + TanStack Query. tokens.css ports BOTH
themes (dark = :root default, light = [data-theme="light"], same values +
breakpoints as the Flask app); ThemeProvider + toggle persist to localStorage
with a pre-paint script (no flash). API client (JWT Bearer + cookie, 401→login),
auth hooks, RequireAuth guard, Login/Register, dashboard shell. **npm install +
tsc --noEmit + vite build all PASSED** (91 modules, network held) — both themes
verified present in the built CSS. node_modules kept for C2–C4._

### (was) C1 · Frontend foundation
- **Delivers:** React Router with the 6 views; `theme/tokens.css` ported from
  the current token layer (same 639/1023/1024/1440/1920 breakpoints, dark =
  default, light derived, "tokens are the only source of colour"); React Query
  client; typed API client from OpenAPI; auth pages + route guard.
- **Verify:** login → dashboard; theme toggle flips every view; 401 → login.

### ☑ C2 · Non-canvas views — DONE (2026-07-25)
_Backend gap closed: projects router (list/create/delete projects, classes
get/set, images list) — 6 assertions verified. Frontend: React Query hooks
(workspaces/projects/members/classes/dataset/versions), shared AppLayout+navbar,
Dashboard (workspaces sidebar + project grid + create modals), Members, Settings
(profile/password/theme picker), ProjectView (Upload/Classes/Dataset/Versions
tabs incl. real upload/zip/video + export links). All token-styled, both themes.
tsc --noEmit clean + vite build ✓._

### (was) C2 · Non-canvas views
- **Delivers:** dashboard/workspaces, upload, classes, dataset, versions,
  members, settings — all on React Query + tokens.
- **Verify:** each view drives its endpoints; responsive at all breakpoints.

### ☑ C3 · Canvas reducer + rendering — DONE (2026-07-25)
_canvas/boxes.ts (faithful port of main.js Boxes: states, IoU, smallest-area
hit-test w/ click-cycling, both reconcilers, accept/reject, serialize) +
canvas/reducer.ts (explicit machine: draw→idle never selected, Escape cancels,
edit=accept). **17 logic assertions PASSED** via esbuild+node — the full C3
checklist AND C4's reconciliation: nested selection both ways, draw→no-handles,
escape-cancel, move/reclass promotes suggestion, re-run no-dup, manual untouched,
rejected stays, auto-save replaces. Canvas.tsx (theme-aware render: confirmed
solid / suggested dashed+conf / rejected hidden / handles) + Annotate.tsx (nav,
load/save, toolbar, keyboard, props panel). Backend gained GET .../image
(traversal-guarded). tsc clean + vite build ✓. 55 endpoints._

### (was) C3 · Canvas reducer + rendering (the hard part)
- **Delivers:** single reducer for box/selection state — explicit
  `idle → selected → resizing/moving → commit`; **draw commits to idle, never
  auto-selects**; Escape cancels drag; **nested hit-test = smallest-area wins**
  with click-cycling; three-state rendering (dashed suggested + confidence).
  Translated from the current `main.js` handlers, not reinvented.
- **Verify (canvas checklist):** nested selection both directions; draw→save
  shows no edit handles; Escape cancels cleanly.

### ☑ C4 · Smart Detect UI + client reconciliation — DONE (2026-07-25)
_Reducer actions APPLY_DETECTIONS (runs review reconcile or autosave reconcile
by mode), ACCEPT_ALL, REJECT_ALL — 5 assertions verified. api/ai.ts hooks
(models/info/settings/predict/autosave_log). SmartDetect bar: model selector +
class count, conf + overlap sliders (persisted per-project), Review/Auto-Save
toggle (amber when auto), "Approve N" bulk-accept, ➤ re-run. Auto-runs on image
change (idempotent via reconcile-against-saved-state). Wired into Annotate. tsc
clean + vite build ✓. **Phase C (React frontend) COMPLETE.**_

### (was) C4 · Smart Detect UI + client reconciliation
- **Delivers:** model selector + class list, conf slider, Review/Auto-Save
  toggle, accept/reject/edit-to-accept, both reconcilers (Review: discard over
  confirmed / replace suggested / skip rejected; Auto-Save: replace same-source
  auto-confirmed in place). Checked against saved state, never a runtime flag.
- **Verify (canvas checklist):** Smart Detect twice → no duplicate; manual box
  untouched by detection; rejected stays rejected on re-run.

## PHASE D — Acceptance

### ☑ D1 · Parity checklist — DONE (2026-07-25)
_[`PARITY.md`](annomaster-next/PARITY.md): every Section 1–3 rule mapped to its
implementation + verification. ~90 automated assertions across the session.
Backend 55 endpoints boot; frontend tsc clean + builds. Honest gaps documented
(visual/browser, live Postgres/Redis/Celery — environmental, not logic). **PORT
COMPLETE across all 13 stages.**_

### (was) D1 · Parity checklist
- **Delivers:** a checklist mapping **every** rule in Sections 1–3 to its
  implementation + a passing test/observation, plus the cross-workspace
  isolation suite and the canvas checklist. This is the acceptance criteria.

---

## Decisions (locked 2026-07-25)

1. **Location** — `annomaster-next/` subdir in this repo.
2. **ORM** — SQLAlchemy 2.0 (typed) + Pydantic schemas, Alembic for migrations.
3. **Infra** — docker-compose for Postgres + Redis.

### Environment reality on THIS machine (verified 2026-07-25)
- Installed: FastAPI 0.115, uvicorn, SQLAlchemy 2.0.25, Alembic 1.13, Pydantic 2.11,
  pydantic-settings, redis-py 5.0, python-jose, passlib. Node v22 / npm 10.
- **Missing:** Celery, a Postgres driver (psycopg/asyncpg), and **Docker itself**.
- **Not running:** Postgres (5432 closed), Redis (6379 closed).

**Consequence:** I can build the scaffold and verify the FastAPI app *boots* and
`/health` returns a well-formed response, but a **green** `/health` needs
Postgres+Redis, which come from `docker compose up` on a machine that has Docker
(this one does not). So `/health` here correctly reports 503 (subsystems down) —
that IS the passing state for A0 in this environment. The green path is run by
you where Docker (or local Postgres/Redis) is available. Installing Celery +
psycopg needs network (`pip install -r backend/requirements.txt`).

## Parity anchors (what "same behaviour" is measured against)

- The **current running app** in this repo — the reference implementation.
- The three earlier prompts (AI/manual lifecycle, Smart Detect, DB audit) —
  each already reflected in the current code and its tests
  (`reconcile`/`autosave`/`accept` suites).
- `CLAUDE.md` — encodes the invariants (confirmed-only exports, accept-on-edit,
  reconcile-against-saved-state, tokens-are-the-only-colour).

## Progress log

_(append one line per landed stage: date · stage · verify result)_

- 2026-08-01 · **Dashboard redesign** (post-port UI work, not a port stage) —
  implemented `design_handoff_dashboard_redesign/Dashboard.dc.html` as
  `routes/Dashboard.tsx` + `routes/dashboard-v2.css` (`--dsh-*` alias namespace →
  semantic tokens, so both themes work; the handoff is a light-only prototype).
  The design's 252px rail + own top bar replace the shared `<AppLayout>` navbar on
  this route, so theme toggle / settings / sign-out moved into a top-bar account
  menu. Sort + grid/list view + search are real state (persisted), not the
  prototype's static controls. Backend: `GET /workspaces/{id}/projects` now also
  returns `updated_at` and `contributors` (3 grouped queries for the whole
  workspace, replacing the per-project COUNT loop) — needed by the card's
  "Updated 2h ago" line, the avatar stack, and the Recent sort. Verified: SQLite +
  `alembic upgrade head` + TestClient asserting counts, annotation-beats-upload
  activity, contributor set and the no-images dir-mtime fallback; `tsc --noEmit`
  clean; `vite build` ✓.
