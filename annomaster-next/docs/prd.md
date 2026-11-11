# AnnoMaster — Product Requirements Document (PRD)

> Scope: **annomaster-next** — the FastAPI + Postgres + Celery + React/Vite rebuild
> of AnnoMaster. The original Flask app (repo root) is the **reference spec** for
> behaviour; the port must match that behaviour and **improve** the UI, not clone it.

## 1. Product summary
AnnoMaster is a collaborative image-annotation platform for building **YOLO object-
detection datasets**. Teams upload images/video/ZIP/YOLO folders into a workspace,
draw bounding boxes (optionally accelerated by a YOLO model — "Smart Detect"),
assign work to annotators, and roll finished work into train/valid/test datasets
that export cleanly to YOLO/COCO/VOC.

## 2. Goals
- **Behaviour parity** with the original app (it is the spec).
- **Better UI/UX**: real dark/light theming, responsive layouts, clean typography
  (Inter), compact cards — the areas the original never finished.
- **Correctness at scale**: one source of truth for image metadata; no drift
  between DB, filesystem, and index; safe exports (human-confirmed labels only).
- **Multi-user**: workspace isolation, roles, batch assignment, locking, audit.

## 3. Personas & roles
| Role | Can |
|------|-----|
| **Owner** | Everything in a workspace: manage members, delete, assign, annotate, export |
| **Editor** | Upload, annotate, assign, add-to-dataset, run Smart Detect, export |
| **Viewer** | Read-only: browse images, datasets, versions |

Auth is JWT (Bearer header **or** `token` cookie **or** `?token=` query param for
`<img>` tags). Roles are enforced per workspace via a `workspace_role(*roles)`
dependency.

## 4. Core features (with acceptance criteria)

### 4.1 Workspaces & projects
- A workspace maps to a folder on disk (`WS-XXXXXX`). A project is a directory +
  `project.json` (classes + settings). Projects are **not** a DB table.
- Deleting a workspace cascades (members, images, locks, assignments) — no orphans.

### 4.2 Upload (four sources, one registration path)
- **Raw images** (JPG/PNG/BMP/TIFF/WEBP).
- **YOLO folder** (`webkitdirectory`): images + `.txt` labels + `data.yaml`/
  `classes.txt`. Incoming class names are **merged** into the project and every
  label's class index is **remapped** to the project's ids.
- **ZIP dataset**: same merge + remap as folder.
- **Video → frames**: a settings dialog asks **FPS** (1/2/5/10/15/24/30), **size**
  (original/1080p/720p/480p), **format** (jpg/png), **split** (none/train/valid/
  test); ffmpeg extracts and registers the frames.
- Duplicate detection is a single `images.md5` column; duplicates are not written.
- **Acceptance**: uploading a labelled YOLO folder whose classes differ in order
  from the project remaps every label so a source "0=person" becomes the project's
  id for "person"; coordinates are preserved.

### 4.3 Active Work (batch cards)
- One card per upload batch showing: source, date, **annotated / raw / null
  progress bar**, **uploader**, **assignment** (who + status + %), and actions:
  **Annotate**, **Assign**, **Add to Dataset**.
- Clicking a card opens the annotator **filtered to that batch**, paginated.

### 4.4 Assignment
- Owner/editor assigns a batch to a workspace member (latest-wins, one per batch).
- The assignment tracks `total_images` / `done_images`; `done_images` increments
  **atomically** on first annotation of each image; auto-advances to `submitted`.

### 4.5 Annotate
- Canvas with **zoom** (wheel, ±, F=fit, 0=1:1) and **pan** (Pan tool, Space-drag,
  middle-drag). Draw mode draws (nested boxes allowed); Select mode edits; Pan mode
  pans. Editing a suggestion **is acceptance**.
- **Class popup** appears on the canvas at the drawn box.
- **Media Library**: filter tabs (All / Annotated / Unannotated) + page-size
  selector (20/50/100) + pager.
- **Image navigator** (bottom-center ‹ n/total ›) and **←/→ (or A/D)** keys.
- **Auto-save**: flush on navigation, debounced save while editing, flush on leave;
  explicit Save + Ctrl+S also.
- **Acceptance**: draw a box, navigate away, come back — the box persisted.

### 4.6 Smart Detect (model-assisted labeling)
- Per-request model discovery from `models/`; **upload a `.pt`** (validated on
  arrival) and use it immediately.
- Confidence + overlap (IoU) sliders; **Review** (suggestions to approve) vs
  **Auto-approve** (writes confirmed, audit-logged) mode.
- **A prediction is a SUGGESTION until a human accepts it.** Confirmed → `.txt`;
  suggested/rejected → `.suggestions.json` sidecar. Exports never contain
  unreviewed detections.

### 4.7 Datasets, versions, export
- **Add to Dataset** (Roboflow-style): only annotated/null images join, with
  train/valid/test split ratios; raw stay in Active Work; **files never move** (a
  DB status/split change). Batch flips to "Add Remaining" if raw remain.
- **Versions**: immutable snapshots of confirmed labels + `data.yaml`.
- **Export**: YOLO / COCO / VOC ZIP, **confirmed labels only**.

## 5. Non-functional
- **Isolation**: every scoped table has `workspace_id` FK `ON DELETE CASCADE`.
- **Concurrency**: annotation **locks** with TTL; SQLite pragmas / Postgres
  equivalents.
- **Auditability**: destructive/auto actions are audit-logged.
- **Theming/responsive**: works in light + dark, reflows without clipping.

## 6. Out of scope (for now)
- Polygon/segmentation annotation (UI stubs exist, disabled).
- Real-time multi-cursor collaboration.
- Cloud model training.

## 7. Environment note
Target is Postgres + Redis + Celery via `docker compose`. This dev machine has
none, so the app is **verified on SQLite** (`ALLOW_SQLITE=true`) with ffmpeg +
ultralytics present. `/health` returns 503 "degraded" locally (Redis down) — that
is the expected local state. See [phase.md](phase.md) and [rules.md](rules.md).
