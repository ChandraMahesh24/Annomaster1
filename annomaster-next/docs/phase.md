# AnnoMaster-next — Phases & Roadmap

Staged, behaviour-parity rebuild. Each phase is independently verifiable. Legend:
✅ done · 🔜 next · ⬜ later.

## Phase A — Foundation ✅
- **A0** Scaffold (FastAPI app factory, Vite app, docker-compose, alembic). ✅
- **A1** Data model (typed SQLAlchemy, enums as CHECKs, `workspace_id` FK CASCADE). ✅
- **A2** Auth (JWT: Bearer / cookie / `?token=`; register/login; login lockout). ✅
- **A3** Workspaces + membership + isolation (`workspace_role`). ✅

## Phase B — Core backend ✅
- **B1** Uploads (single / folder-`webkitdirectory` / ZIP / video) through one
  registration path; `md5` dedup; **class merge + label remap** for labelled sets. ✅
- **B2** Annotations (confirmed `.txt` + `.suggestions.json` sidecar) + locking +
  atomic assignment `done_images` increment. ✅
- **B3** Smart Detect (per-request model discovery, cached YOLO instances, `.pt`
  upload with validation, predict, per-project `settings.ai`). ✅
- **B4** Datasets / versions / exports (add-to-dataset = DB flip; immutable
  versions; YOLO/COCO/VOC ZIP, confirmed-only). ✅

## Phase C — React frontend ✅
- Shell (`Workspace.tsx`), sections, canvas engine (reducer + boxes + Canvas),
  React Query data layer. ✅

## Phase D — Parity & correction ✅
- **D1** Behaviour-parity pass vs the original; 2 logic fixes (hit-test tie-break →
  last-drawn; login lockout no longer resets count on lock). ✅
- **DB guard**: loud RuntimeError on a SQLite URL without `ALLOW_SQLITE`; no silent
  SQLite fallback; Postgres fail-fast timeouts. ✅

## Phase U — UI parity + redesign ✅
- **U0–U7** every screen on the original markup + ported CSS, then **redesigned**
  where the original fell short (theme, responsive, fonts). ✅
- **Typography**: switched UI font Sora → **Inter**; removed ~80 hardcoded `'Sora'`. ✅
- **Light-mode fixes**: hardcoded white-on-fill contrast bugs on the upload page. ✅

## Phase F — Feature work (post-parity) ✅ so far
- **Video frame-extraction dialog** (FPS/size/format/split) + backend params. ✅
- **ZIP / YOLO-folder** class merge + label class-id remap. ✅
- **`run.py`** one-command launcher (backend + frontend, UTF-8 safe). ✅
- **Active Work batch cards**: progress + assignment + Annotate/Assign/Add-to-Dataset,
  compact + responsive; **Assign** and **Add-to-Dataset** endpoints. ✅
- **Completed Datasets** card (real `.upds-card`, split bar) replacing the stub. ✅
- **Annotate improvements**:
  - Canvas **zoom + pan** (wheel/±/F/0, Pan tool, Space/middle-drag). ✅
  - **Class popup on the canvas** at the drawn box. ✅
  - **Media Library** filter tabs + page-size (20/50/100) + pager. ✅
  - **Image navigator** (‹ n/total ›) + **←/→ / A/D** keys. ✅
  - **Auto-save** (flush-on-nav + debounce + flush-on-unmount). ✅
  - Smart Detect **closed by default** + resets per batch. ✅
  - Smart Detect **model upload** (`.pt`) from the bar. ✅
  - Smart Detect **default position beside** the draw-toolbar. ✅

## 🔜 Next candidates
- Right-panel extras: **Image Info** (dimensions), **YOLO-format** text view,
  **Image Notes**.
- Media Library **collapse** + **Null** filter tab.
- **Per-dataset cards** in Completed Datasets (needs `GET /datasets` grouping
  in-dataset images by batch) with view / export / delete.
- Smart Detect bar **drag-to-reposition** (CSS is ready: `.is-moved`/`.is-dragging`).
- Light-mode audit across Annotate / Dataset / Versions / Classes.

## ⬜ Blocked (needs infra this machine lacks)
- Prove Postgres: `/health` green + `psql` tables. Needs a running Postgres/Redis
  (Docker). Locally the app is verified on SQLite; `/health` = 503 degraded.

## Verification log convention
Each landed item is verified by a `TestClient` script (results written to a file)
and/or `tsc --noEmit && vite build`. See [rules.md](rules.md) §F.
