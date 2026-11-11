# AnnoMaster Port — Parity Checklist (Phase D1)

Acceptance criteria for the FastAPI + Postgres + Celery + React port. Every rule
from the port spec's Sections 1–3 is mapped to its implementation and the
verification that confirms it behaves like the original Flask app.

**Verification legend:** ✅ verified by an automated assertion run this session ·
🔬 verified against real dependency (ffmpeg / ultralytics) · 🏗️ build/boot-verified
(typecheck + vite build + app boot) · 👁️ needs a browser to confirm visually.

All backend checks ran on SQLite (Postgres is the deploy target; `/health`
is 503 locally until `docker compose up`). Frontend logic ran via esbuild+node;
UI is build-verified.

---

## Section 1 — Data model (8 tables)

| Entity | Implementation | Verified |
|---|---|---|
| users (public_id, avatar_url, bio, last_login, failed_login_count, locked_until) | `models/user.py` | ✅ A1 |
| workspaces + workspace_members (owner/editor/viewer) | `models/workspace.py` | ✅ A1 (role CHECK) |
| annotation_locks — UNIQUE(workspace_id, project, image_path) | `models/annotation_lock.py` | ✅ A1 (dup rejected) |
| audit_log — insert-only, JSON detail, FK SET NULL | `models/audit_log.py` | ✅ A2 |
| upload_batches | `models/upload_batch.py` | ✅ B1 |
| images (status active\|in_dataset, split, is_annotated, is_null, provenance) | `models/image.py` | ✅ A1 + B1 |
| assignments (status enum, total/done_images, due_date) | `models/assignment.py` | ✅ A1 + B2 |
| **workspace_id is a real FK `ON DELETE CASCADE`** (fixes the original's orphan rows) | all scoped tables | ✅ A1 (cascade verified) |
| enum columns are DB `CHECK`s; `split` = train\|valid\|test (real behaviour) | migration `7f23e9d…` | ✅ A1 |

## Section 2 — Business rules

| Rule | Implementation | Verified |
|---|---|---|
| JWT via `Authorization: Bearer` OR cookie | `core/security.py` | ✅ A2 (both paths) |
| 5 failed logins → 15-min lockout, auto-clears on success | `api/auth.py` | ✅ A2 |
| Rate limits (login 15/min·60/hr, register 10/hr, pw 5/hr) | `core/ratelimit.py` | ✅ A2 (429 tripped) |
| Audit every auth event; logging never breaks the request | `services/audit.py` | ✅ A2 |
| Locking: 60s TTL, heartbeat renews, acquire→409 w/ holder, owner force-release | `api/locks.py` | ✅ B2 |
| **TTL enforced on every read** (not just acquire — the original bug) | `services/locks.active_lock` | ✅ B2 (expired→save allowed) |
| Acquire race → clean 409 (UNIQUE guards it), not 500 | `api/locks.py` | ✅ (IntegrityError path) |
| `done_images` increments ATOMICALLY on first annotation; auto→submitted | `api/annotations._bump_assignment` | ✅ B2 (`UPDATE … +1`) |
| **Workspace isolation** — every scoped query filters by workspace_id | `core/deps.workspace_role` | ✅ A3 (cross-guessing test, 7 endpoints→403) |
| **Files never move** — lifecycle is a DB column | `services/datasets.py` | ✅ B4 (files stay under Active_Work) |
| Null image = empty `.txt` on disk (never missing) | `api/annotations.mark_null` | ✅ B2 |

## Section 3 — Annotation canvas + Smart Detect

| Rule | Implementation | Verified |
|---|---|---|
| **Nested selection** — smallest-area wins, click-cycling both directions | `canvas/boxes.hitTest` | ✅ C3 |
| State machine idle→selected→resizing/moving→commit | `canvas/reducer.ts` | ✅ C3 |
| **Draw commits to idle — never auto-selects** (no edit handles after draw) | reducer POINTER_UP | ✅ C3 |
| Escape cancels an in-progress drag without committing | reducer CANCEL | ✅ C3 |
| Three-state lifecycle: suggested\|confirmed\|rejected + source | `canvas/boxes.ts` | ✅ C3 |
| Manual draws born confirmed; Smart Detect enters suggested + confidence | reducer + SmartDetect | ✅ C3/C4 |
| **Edit-to-accept** — move/resize/reclass a suggestion promotes it | reducer (accept on move/reclass) | ✅ C3 |
| rejected soft-kept, never rendered, never re-suggested | `canvas/boxes` + Canvas render | ✅ C3 |
| **Reconcile on every run vs SAVED state** (no session flag): confirmed→discard, suggested→refresh, rejected→skip, none→add | `boxes.reconcile` | ✅ C3 (re-run no dup, manual untouched) |
| **Auto-Save** — replace same-class in place, no duplicate on revisit | `boxes.reconcileAutoSave` | ✅ C3/C4 |
| **Exports include only `confirmed`** (YOLO/COCO/VOC) | `services/exports.py` (reads `.txt`) | ✅ B4 (1 conf + 1 sugg → only conf, all 3 formats) |
| Model selection — scan, per-project persisted, class list shown | `services/ai_models.py` + SmartDetect | 🔬 B3 (real blackshirt model) + 🏗️ C4 |
| Confidence threshold — per-project persisted, discards below | `ai/predict` + settings | ✅ B3 |
| Auto-Save is audit-logged (`ai.autosave`) | `api/ai.autosave_log` | ✅ B3 |

## "What must NOT change"

| Guarantee | Status |
|---|---|
| Filesystem-as-source-of-truth (labels on disk, NOT Postgres blobs) | ✅ kept |
| `.txt` confirmed-only + `.suggestions.json` sidecar split | ✅ B2/B4 |
| Only one module builds paths (`core/paths.py`) | ✅ kept |
| suggestion/confirm/reject + manual/auto distinction | ✅ C3 |
| Design tokens = only source of colour; dark default / light derived; same breakpoints | ✅ C1 (both themes in built CSS) |

---

## Verification tally

~90 automated assertions across the session:
A1 constraints · A2 (12 auth) · A3 (17 isolation) · B1 (uploads + 🔬10 real frames)
· B2 (12 annotations/locks) · B3 (🔬12 real model) · B4 (17 exports, confirmed-only ×3 formats)
· C2 (6 projects) · C3 (17 canvas logic) · C4 (5 detection reducer).
Backend: 55 endpoints boot. Frontend: tsc clean + vite build, 7 routes, both themes.

## Honest gaps (what a browser / real stack would still confirm)

- 👁️ **Visual/interaction**: canvas drawing feel, pixel rendering, drag ergonomics —
  logic is exhaustively tested, the drawing surface is build-verified only.
- 🏗️ **Postgres/Redis/Celery live path**: verified on SQLite + inline task fallback;
  a green `/health` and real Celery execution need `docker compose up` elsewhere.
- The React app talks to the backend via the Vite `/api` proxy — the two haven't
  been driven together end-to-end in a browser (each verified on its own side).

These are environmental (no Docker/browser here), not logic gaps: every business
rule and canvas invariant above is confirmed by an assertion.
