# AnnoMaster — Industry-Ready Upgrade Report

**Last updated:** June 14, 2026
**Scope:** Multi-user security hardening + enterprise collaboration features + team tracking + dataset management + upload UI fixes + assignment feature
**Files changed:** 12 modified · 8 created · 0 deleted (across all phases)

---

## Summary

The baseline codebase had a solid architecture (clean api/core/models split, JWT auth, role-based access) but had five critical vulnerabilities that would cause data loss or security breaches in a real team environment. This upgrade fixes all five and adds three new enterprise modules (locking, audit log, per-user stats) without changing any existing API contracts or breaking existing frontend code.

---

## 1. Critical Security Fixes

### 1.1 Server-Side Authentication on All Page Routes

**File:** `app/__init__.py`

**Problem before:**
All HTML page routes (`/`, `/pages/annotate`, `/pages/upload`, `/workspace/<id>/members`, `/settings`) had zero server-side auth. Any person who knew the URL could open them without logging in. A comment in the code even said _"Auth is handled client-side by JS"_ — which means disabling JavaScript bypassed all access control entirely.

**Fix:**
Added a `_require_auth()` helper inside `_register_page_routes()` that calls `get_current_user()` on every page request. If the token is missing or invalid, Flask returns `redirect('/login')` before the template is ever rendered.

```python
# BEFORE — no protection
@app.route('/')
def index():
    return render_template('workspace/dashboard.html')

# AFTER — server enforces auth
@app.route('/')
def index():
    r = _require_auth()
    return r if r else render_template('workspace/dashboard.html')
```

---

### 1.2 Atomic Annotation File Writes

**File:** `app/core/yolo.py` → `write_yolo_label()`

**Problem before:**
`lbl_path.write_text(''.join(lines))` — a single call that writes directly to the final file. If the server process was killed mid-write (power cut, OOM killer, Ctrl+C during a large save) the label file would be left **half-written and permanently corrupt**. The YOLO parser would then silently skip those broken lines.

**Fix:**
Write to a UUID-named `.tmp` sibling file first, then call `os.replace()` which is atomic on both Linux (POSIX rename) and Windows (NTFS). Readers always see either the old complete file or the new complete file — never a partial one.

```python
# BEFORE
lbl_path.write_text(''.join(lines), encoding='utf-8')

# AFTER — atomic write
tmp = lbl_path.with_suffix(f'.{uuid.uuid4().hex[:8]}.tmp')
try:
    tmp.write_text(''.join(lines), encoding='utf-8')
    os.replace(str(tmp), str(lbl_path))   # atomic on POSIX + NTFS
finally:
    tmp.unlink(missing_ok=True)
```

---

### 1.3 Rate Limiting on Auth Endpoints

**File:** `app/api/auth.py`, `requirements.txt`

**Problem before:**
No rate limiting anywhere. An attacker could send unlimited login attempts per second — a trivial brute-force attack against any account.

**Fix:**
Added `flask-limiter` (in-memory storage, swap to Redis in production) with per-route decorators:

| Endpoint | Limit |
|----------|-------|
| `POST /api/auth/login` | 15 per minute · 60 per hour |
| `POST /api/auth/register` | 10 per hour |
| `POST /api/auth/change-password` | 5 per hour |

`requirements.txt` additions:
```
flask-limiter>=3.5.0
limits>=3.6.0
```

---

### 1.4 Account Lockout After Repeated Failed Logins

**Files:** `app/models/user.py`, `app/api/auth.py`, `app/utils/security.py`

**Problem before:**
No lockout logic. An attacker could attempt passwords forever without any consequence beyond a 401 response.

**Fix:**
Added two new columns to the `users` table:
- `failed_login_count` (Integer, default 0)
- `locked_until` (DateTime, nullable)

Logic: 5 wrong passwords → account locked for 15 minutes. Lock is automatically cleared on next successful login.

```python
# New User model methods
def record_failed_login(self):
    self.failed_login_count += 1
    if self.failed_login_count >= 5:
        self.locked_until = datetime.utcnow() + timedelta(minutes=15)

def record_successful_login(self):
    self.failed_login_count = 0
    self.locked_until = None
    self.last_login = datetime.utcnow()
```

The `login_required` decorator also checks lockout status so even a valid token from a locked account is rejected at the API layer.

---

### 1.5 Concurrent Annotation Conflict Detection

**File:** `app/api/annotations.py`

**Problem before:**
Two annotators opening the same image simultaneously would silently overwrite each other. User A saves → User B saves 2 seconds later → A's work is gone with no warning. This is a guaranteed data-loss scenario in any team larger than one person.

**Fix:**
`POST /api/.../annotations` now calls `_check_lock_conflict()` before writing. If another user holds an active `AnnotationLock` for that image, the save is rejected with HTTP 409 and the response tells the client exactly who has the lock. (See Section 3 for the full locking system.)

```python
conflict = _check_lock_conflict(workspace_id, project, rel)
if conflict:
    return jsonify(conflict), 409   # "Image is being edited by @alice"
```

---

## 2. Enhanced User Model

**File:** `app/models/user.py`

New columns added to the `users` table (all nullable / have defaults — no migration needed for existing rows):

| Column | Type | Purpose |
|--------|------|---------|
| `avatar_url` | String(500) | Profile picture URL (upload or external link) |
| `bio` | String(500) | Short user bio shown on team member lists |
| `last_login` | DateTime | Timestamp of most recent successful login |
| `updated_at` | DateTime | Auto-updated on every profile change |
| `failed_login_count` | Integer | Brute-force counter (see 1.4) |
| `locked_until` | DateTime | Lockout expiry timestamp (see 1.4) |

`to_dict()` now accepts `include_private=True` flag for admin endpoints that need to see lockout state.

---

## 3. New Feature — Image-Level Annotation Locking

**New files:**
- `app/models/annotation_lock.py` — `annotation_locks` DB table
- `app/api/locks.py` — 5 REST endpoints

### How it works

When a user opens an image in the annotation editor:
1. Frontend calls `POST /locks/acquire` → server creates a 60-second TTL lock
2. Frontend sends `POST /locks/heartbeat` every 30 s to renew
3. On navigate-away or tab close → `POST /locks/release`
4. `GET /locks` (project-wide) returns all active locks → powers "who is editing" dots on the image filmstrip

If User B tries to open an image that User A has locked:
- Acquire returns HTTP 409 with `{"error": "@alice is editing this image", "lock": {...}}`
- The annotation save endpoint also enforces the lock as a second layer of protection

### API Reference

| Method | Path | Role | Description |
|--------|------|------|-------------|
| `GET` | `/locks` | any | List all active locks in a project |
| `POST` | `/locks/acquire` | editor+ | Acquire or renew own lock |
| `POST` | `/locks/release` | editor+ | Release own lock |
| `POST` | `/locks/heartbeat` | editor+ | Renew all own locks in project |
| `POST` | `/locks/force-release` | owner | Break another user's lock |

### Database table

```
annotation_locks
  id            PK
  workspace_id  INT   NOT NULL
  project       TEXT  NOT NULL
  image_path    TEXT  NOT NULL
  locked_by     FK → users.id  (CASCADE DELETE)
  acquired_at   DATETIME
  expires_at    DATETIME        INDEX
  UNIQUE (workspace_id, project, image_path)
```

---

## 4. New Feature — Audit Log

**New files:**
- `app/models/audit_log.py` — `audit_log` DB table + `log_action()` helper
- `app/api/audit.py` — 3 read-only REST endpoints

### What gets logged

| Action | Trigger |
|--------|---------|
| `auth.login` | Successful login |
| `auth.login_failed` | Wrong password |
| `auth.login_failed_lockout` | Password failure that triggers lockout |
| `auth.login_locked` | Attempt while already locked |
| `auth.register` | New account created |
| `auth.profile_update` | Username / email / bio changed |
| `auth.password_change` | Password changed |
| `auth.account_delete` | Account permanently deleted |
| `annotation.save` | Any annotation save (includes bbox_count) |
| `annotation.null` | Image marked as unannotated/null |
| `lock.force_release` | Owner breaks another user's lock |

All log entries are immutable. The `log_action()` helper swallows its own exceptions so a logging failure never breaks the caller's HTTP response.

### API Reference

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/workspaces/<id>/audit` | Workspace-wide activity feed |
| `GET` | `/api/workspaces/<id>/projects/<p>/audit` | Project activity feed |
| `GET` | `/api/workspaces/<id>/projects/<p>/audit/actors` | Users active in a project (for filter UI) |

Query parameters on all feed endpoints:
- `page`, `per_page` (max 200)
- `action` — filter by prefix, e.g. `annotation` or `auth.login`
- `user_id` — show only one user's actions

### Database table

```
audit_log
  id            PK
  user_id       FK → users.id  (SET NULL on delete)
  action        VARCHAR(80)   INDEX
  workspace_id  INT           ]
  project       VARCHAR(200)  ]— composite INDEX
  image_path    TEXT
  detail        TEXT  (JSON blob — bbox_count, old/new values, etc.)
  ip_address    VARCHAR(50)
  timestamp     DATETIME      INDEX
```

---

## 5. New Feature — Per-Annotator Statistics

**New file:** `app/api/user_stats.py` — 3 REST endpoints

Statistics are derived from the `audit_log` table (`action = 'annotation.save'`) so there are no extra counters to maintain — they are always accurate.

### API Reference

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/workspaces/<id>/projects/<p>/stats/users` | Annotation leaderboard for one project |
| `GET` | `/api/workspaces/<id>/stats/users` | Leaderboard across all projects |
| `GET` | `/api/workspaces/<id>/stats/me` | Current user's own stats, broken down by project |

### Example response (`/stats/users`)

```json
{
  "stats": [
    {
      "user_id": 3,
      "username": "alice",
      "avatar_url": null,
      "count": 1842,
      "last_active": "2026-06-13T14:22:05"
    },
    {
      "user_id": 7,
      "username": "bob",
      "avatar_url": null,
      "count": 934,
      "last_active": "2026-06-13T11:08:41"
    }
  ]
}
```

---

## 6. New API Endpoints — Complete Reference

All new endpoints follow the same auth pattern as existing ones (`@login_required` + `@workspace_role_required`).

### Annotation Locks

```
GET    /api/workspaces/<id>/projects/<p>/locks
POST   /api/workspaces/<id>/projects/<p>/locks/acquire       body: {path}
POST   /api/workspaces/<id>/projects/<p>/locks/release       body: {path}
POST   /api/workspaces/<id>/projects/<p>/locks/heartbeat
POST   /api/workspaces/<id>/projects/<p>/locks/force-release body: {path}  [owner only]
```

### Audit Log

```
GET    /api/workspaces/<id>/audit                            ?page&per_page&action&user_id
GET    /api/workspaces/<id>/projects/<p>/audit               ?page&per_page&action&user_id
GET    /api/workspaces/<id>/projects/<p>/audit/actors
```

### User Stats

```
GET    /api/workspaces/<id>/stats/users
GET    /api/workspaces/<id>/stats/me
GET    /api/workspaces/<id>/projects/<p>/stats/users
```

---

## 7. Breaking Changes

**None.** All existing API endpoints, URL shapes, request bodies, and response schemas are unchanged. The frontend JavaScript (`main.js`, `features/`) does not need any modifications to keep working.

The only behaviour change a user will notice:
- Navigating directly to `/pages/annotate` without a token now redirects to `/login` instead of loading the page (this is the intended security fix)
- Login with a wrong password 5 times → 15-minute lockout with a clear error message

---

## 8. Database Migration

New tables are created automatically by `db.create_all()` on first run after the upgrade. No manual migration command is needed for new installations.

For **existing installations** (upgrading from baseline):

```bash
# Install new packages
pip install flask-limiter limits

# Run the migration script — safe to run multiple times, skips existing tables/columns
python migrate_db.py

# Then start the app normally
python run.py
```

`migrate_db.py` handles all schema changes via raw `sqlite3` ALTER TABLE and CREATE TABLE statements. It is idempotent — every step checks if the column or table already exists before acting. This avoids any dependency on flask-migrate or Alembic.

---

## 9. Files Changed — Phase 1 Only

*See Section 11 for the complete combined file list including Phase 2.*

### Modified (Phase 1)

| File | Change |
|------|--------|
| `requirements.txt` | Added `flask-limiter>=3.5.0`, `limits>=3.6.0` |
| `app/__init__.py` | Server-side auth on page routes · registered 3 new blueprints · imports new models |
| `app/models/user.py` | 6 new columns · `record_failed_login()` · `record_successful_login()` · `is_locked()` |
| `app/utils/security.py` | Lockout check in `login_required` · robust `get_current_user()` |
| `app/api/auth.py` | Rate limits · lockout enforcement · audit log calls · min password 8 chars |
| `app/core/yolo.py` | `write_yolo_label()` — atomic temp-file write pattern |
| `app/api/annotations.py` | Lock conflict check on POST · audit log on every save · lock info on GET |

### Created (Phase 1)

| File | Purpose |
|------|---------|
| `app/models/audit_log.py` | `AuditLog` model + `log_action()` helper |
| `app/models/annotation_lock.py` | `AnnotationLock` model (60-second TTL image locks) |
| `app/api/locks.py` | Acquire / release / heartbeat / force-release endpoints |
| `app/api/audit.py` | Activity feed endpoints (workspace + project) |
| `app/api/user_stats.py` | Per-annotator annotation count leaderboard |

---

## 10. New Feature — Team Tracking & Dataset Management (Phase 2)

**New files:**
- `app/models/upload_batch.py` — `UploadBatch` model
- `app/models/image.py` — `Image` model
- `app/models/assignment.py` — `Assignment` model
- `app/models/__init__.py` — updated to register all models

### Design principle — Files Never Move

The previous approach moved image files between `Active_Work/` and `Completed_Datasets/` folders. This is wrong for enterprise use:

| File-move (old) | DB-status (new) |
|-----------------|-----------------|
| Files scatter across folders | Files stay in one location forever |
| Can't re-assign split (train→val) without moving again | Change `split` column with one SQL UPDATE |
| History is lost when files move | Full audit trail in DB |
| Breaks if OS rename fails mid-batch | Atomic DB transaction |
| Can't query "who uploaded this?" | `uploaded_by` FK on every image |

**New rule:** `rel_path` on the `images` table is set once on upload and never changes. Stage changes are tracked by updating `images.status`.

---

### New Table — `upload_batches`

Tracks every bulk upload operation.

```
upload_batches
  id            PK
  workspace_id  INT   NOT NULL
  project       TEXT  NOT NULL
  batch_name    TEXT             ← optional label e.g. "Site-A Day-1"
  source        TEXT  DEFAULT 'upload'   ← 'upload' | 'zip' | 'video'
  uploaded_by   FK → users.id  (SET NULL on delete)
  uploaded_at   DATETIME
  total_images  INT   DEFAULT 0
```

**What you can answer:**
```sql
SELECT u.username, b.batch_name, b.total_images, b.uploaded_at
FROM upload_batches b JOIN users u ON b.uploaded_by = u.id
WHERE b.project = 'site-survey'
ORDER BY b.uploaded_at DESC;
```

---

### New Table — `images`

One row per image. Tracks the full lifecycle.

```
images
  id            PK
  workspace_id  INT   NOT NULL
  project       TEXT  NOT NULL
  batch_id      FK → upload_batches.id  (SET NULL on delete)
  filename      TEXT  NOT NULL
  rel_path      TEXT  NOT NULL    ← NEVER changes after insert

  status        TEXT  DEFAULT 'active'   ← 'active' | 'in_dataset'
  split         TEXT  NULL               ← 'train' | 'val' | 'test'

  is_annotated  BOOL  DEFAULT 0
  is_null       BOOL  DEFAULT 0          ← background image, no objects

  uploaded_by   FK → users.id  (SET NULL)
  uploaded_at   DATETIME
  annotated_by  FK → users.id  (SET NULL)
  annotated_at  DATETIME
  reviewed_by   FK → users.id  (SET NULL)
  reviewed_at   DATETIME
  assigned_to   FK → users.id  (SET NULL)   ← current responsible annotator
```

#### Null / Background Images

In YOLO format, an image with no objects must have an **empty `.txt` label file** (not a missing file). The DB tracks this with `is_null=True`.

| Image state | `is_annotated` | `is_null` | Label file on disk |
|-------------|:-:|:-:|---|
| Not yet worked on | `False` | `False` | Does not exist |
| Has bounding boxes | `True` | `False` | `.txt` with content |
| Background (no objects) | `True` | `True` | `.txt` exists, 0 bytes |

**What you can answer:**
```sql
-- Who annotated each image?
SELECT i.filename, u.username, i.annotated_at
FROM images i JOIN users u ON i.annotated_by = u.id
WHERE i.batch_id = 42;

-- How many null images vs annotated?
SELECT
  SUM(CASE WHEN is_null=1 THEN 1 ELSE 0 END)        AS null_images,
  SUM(CASE WHEN is_null=0 AND is_annotated=1 THEN 1 ELSE 0 END) AS annotated,
  SUM(CASE WHEN is_annotated=0 THEN 1 ELSE 0 END)    AS pending
FROM images WHERE project = 'site-survey';
```

---

### New Table — `assignments`

Owner assigns a batch to an annotator. Tracks progress automatically.

```
assignments
  id            PK
  workspace_id  INT   NOT NULL
  project       TEXT  NOT NULL
  batch_id      FK → upload_batches.id  (CASCADE delete)
  assigned_to   FK → users.id  (CASCADE delete)   ← annotator
  assigned_by   FK → users.id  (SET NULL)          ← owner
  assigned_at   DATETIME
  due_date      DATETIME  NULL
  note          TEXT      NULL
  status        TEXT  DEFAULT 'pending'
                     ← 'pending' | 'in_progress' | 'submitted' | 'approved' | 'rejected'
  total_images  INT   DEFAULT 0
  done_images   INT   DEFAULT 0
```

**Status lifecycle:**
```
pending → in_progress → submitted → approved
                               ↓
                           rejected → (annotator fixes) → submitted
```

`done_images` increments automatically when an image in the assignment is
annotated for the first time. When `done_images == total_images` the status
auto-advances to `submitted`.

**What you can answer:**
```sql
-- Progress per annotator on a batch
SELECT u.username,
       a.total_images,
       a.done_images,
       ROUND(a.done_images * 100.0 / a.total_images, 1) AS pct,
       a.status,
       a.due_date
FROM assignments a JOIN users u ON a.assigned_to = u.id
WHERE a.batch_id = 42;
```

---

### YOLO Version ZIP Format

When a version is created, the export generates a ZIP with this structure:

```
v1.0.zip
├── data.yaml
├── train/
│   ├── images/   ← jpg/png files for training split
│   └── labels/   ← .txt files (empty file = null/background image)
├── val/
│   ├── images/
│   └── labels/
└── test/
    ├── images/
    └── labels/
```

`data.yaml` content:
```yaml
path: .
train: train/images
val:   val/images
test:  test/images

nc: 3
names:
  0: person
  1: car
  2: sign
```

No files are duplicated on disk permanently. The ZIP is generated on-demand by streaming images and labels from their original `rel_path` locations into the archive.

---

## 11. Files Changed — Full List (Phase 1 + Phase 2)

### Modified

| File | Change |
|------|--------|
| `requirements.txt` | Added `flask-limiter>=3.5.0`, `limits>=3.6.0` |
| `app/__init__.py` | Server-side auth on page routes · registered 3 new blueprints · imports new models |
| `app/models/__init__.py` | Registers all 7 models so SQLAlchemy builds the full schema |
| `app/models/user.py` | 6 new columns · `record_failed_login()` · `record_successful_login()` · `is_locked()` |
| `app/utils/security.py` | Lockout check in `login_required` · robust `get_current_user()` |
| `app/api/auth.py` | Rate limits · lockout enforcement · audit log calls · min password 8 chars |
| `app/core/yolo.py` | `write_yolo_label()` — atomic temp-file write pattern |
| `app/api/annotations.py` | Lock conflict check on POST · audit log on every save · lock info on GET |
| `migrate_db.py` | Extended to create 3 new tables (upload_batches, images, assignments) |

### Created

| File | Purpose |
|------|---------|
| `app/models/audit_log.py` | `AuditLog` model + `log_action()` helper |
| `app/models/annotation_lock.py` | `AnnotationLock` model (60-second TTL image locks) |
| `app/models/upload_batch.py` | `UploadBatch` model — who uploaded which batch and when |
| `app/models/image.py` | `Image` model — per-image lifecycle, null tracking, assignment |
| `app/models/assignment.py` | `Assignment` model — who is assigned to annotate what, with progress |
| `app/api/locks.py` | Acquire / release / heartbeat / force-release endpoints |
| `app/api/audit.py` | Activity feed endpoints (workspace + project) |
| `app/api/user_stats.py` | Per-annotator annotation count leaderboard |

---

## 12. What Is Still Recommended (Next Steps)

| Priority | Feature | Effort |
|----------|---------|--------|
| High | Wire upload API to create `UploadBatch` + `Image` rows on every upload | Small |
| High | Assignment API — endpoints to assign batches, view progress, approve/reject | Medium |
| High | YOLO ZIP version generator — stream ZIP on-demand from DB + filesystem | Medium |
| Medium | Review/QA workflow — annotator submits → reviewer approves/rejects with comments | Large |
| Medium | Real-time presence (Flask-SocketIO) — live "who is on which image" without polling | Medium |
| Medium | Email notifications — invite emails, task assigned, review completed | Medium |
| Low | Async job queue (Celery/RQ) — move video extraction & version creation off the request thread | Medium |
| Low | PostgreSQL migration — SQLite is fine up to ~10 concurrent writers; beyond that switch DB | Small |
| Low | S3/cloud storage backend — for multi-server or cloud deployments | Large |

---

*Phase 1 completed: June 13, 2026. Phase 2 (team tracking + dataset management) completed: June 13, 2026. Phase 3 (upload UI fixes + assignment feature) completed: June 14, 2026.*

---

## 13. Phase 3 — Upload UI Fixes & Assignment Feature

**Date:** June 14, 2026
**Files changed:** 5 modified · 0 created

---

### 13.1 Fix — "No Images Yet" After Clicking a Batch (img_dir missing)

**File:** `app/api/uploads.py` → `api_batch_media`

**Problem:** When a batch directory did not yet exist on disk (e.g. created but nothing saved yet), `api_batch_media` crashed with HTTP 500 because `img_dir.iterdir()` raised `FileNotFoundError`.

**Fix:** Added an explicit guard at the top of the handler:

```python
if not img_dir.exists():
    return jsonify({'media': [], 'annotated': [], 'null_paths': [], 'classes': []})
```

---

### 13.2 Fix — No Progress Bar During Raw Image Upload

**Files:** `static/js/main.js`, `static/js/engine/canvas.js` → `_handleFilesDrop`

**Problem:** The `_upSetPageProgress()` call existed only in the video-frame-extraction path. The raw-image upload loop (PNG/JPG files dropped directly) never called it, so the progress bar stayed hidden throughout the entire upload.

**Fix:** Added `_upSetPageProgress(0, 'Uploading images…', …)` before the loop and a per-iteration call inside the loop with a percentage calculated from the file index:

```js
this._upSetPageProgress(0, 'Uploading images…', files.length, 0);
// inside loop:
const pct2 = Math.round(((i + 1) / files.length) * 100);
this._upSetPageProgress(pct2, 'Uploading images…', files.length, i + 1);
```

---

### 13.3 Fix — Dark `udr-modal` in Light Theme

**File:** `static/css/main.css`

**Problem:** The upload-delete-review modal (`.udr-modal`) used CSS variables that resolve to dark colours. When the user switched to light mode (`html.light-mode`), the modal remained dark with illegible text.

**Fix:** Added a `html.light-mode` override block after the existing `.udr-*` rules that forces light backgrounds, dark text, and light-toned borders on all `.udr-*` elements.

---

### 13.4 Fix — Batch Cards Refresh After Video Frame Extraction

**Files:** `static/js/main.js`, `static/js/engine/canvas.js` → `startExtractFrames`

**Problem:** After extracting frames from a video, the media panel refreshed but the Active Work batch cards did not, so the new batch appeared empty until the user manually reloaded.

**Fix:** Added `await this._loadUploadBatches()` immediately after `await this._loadMedia()` at the end of `startExtractFrames`.

---

### 13.5 Fix — "No Images Yet" for Raw Image Uploads (Duplicate Detection)

**File:** `app/api/uploads.py` → `api_upload`

**Root cause:** `db_index.add_image()` computes an MD5 hash for every uploaded file and checks it against a project-wide `hashes` table. If the same image was ever uploaded to **any** batch in the same project, `add_image()` returns `{'duplicate': True}`. The original code then called `dest.unlink(missing_ok=True)` — deleting the file from disk — and returned early with `success: False`. Because the JS upload loop never checked the response body, all images were silently deleted. `_count_batch()` counts physical files on disk, so it found zero → the card showed "No images yet".

**Fix:** Removed the `dest.unlink()` + early return. The file stays on disk in the new batch even when the MD5 already exists in the hashes table. `_count_batch()` now correctly counts the uploaded images.

```python
# BEFORE
if result.get('duplicate'):
    dest.unlink(missing_ok=True)        # ← deleted the file
    return jsonify({'success': False, 'duplicate': True, ...})

# AFTER
if result.get('duplicate'):
    pass    # keep the file — let it live in this new batch
```

---

### 13.6 Feature — Assignment Info on Active Work Batch Cards

**Files:** `static/js/main.js`, `static/js/engine/canvas.js` → `_buildBatchCard`

**What changed:** Each batch card now renders:
- **Uploader chip** — shows the username of the person who created the batch
- **Assignment chip** — shows "Unassigned" (grey) or "→ username (role)" (green) pulled from the `assignment` object returned by the API
- **Assign / Reassign button** in the card footer — opens the assignment modal
- Colour-coded status badge using a `statusMeta` map (pending → blue, in_progress → amber, submitted → purple, approved → green, rejected → red)

**CSS additions (`static/css/main.css`):**
- `.uhp-meta-row`, `.uhp-meta-chip` — uploader and assignment chip styles
- `.uhp-btn.assign` (indigo) and `.uhp-btn.reassign` (amber)
- `html.light-mode` overrides for all new chip classes

---

### 13.7 Feature — Assignment Modal

**Files:** `static/js/main.js`, `static/js/engine/canvas.js` → `_showAssignModal` (new method)

A full-screen overlay modal that appears when the Assign / Reassign button is clicked.

**Behaviour:**
1. Fetches workspace members from `GET /api/workspaces/<id>/members` (only members of the current workspace are listed — external users are excluded)
2. Renders a responsive auto-fill grid of member cards with avatar initial, display name, and role badge
3. In reassign mode, shows a "Currently assigned to" block at the top with a Remove button
4. Optional note textarea for assignment instructions
5. Confirm button disabled until a member is selected; shows spinner during the API call
6. Calls `POST /api/workspaces/<id>/projects/<p>/uploads/<uid>/assign` on confirm or `DELETE` on remove

**CSS additions (`static/css/main.css`):**
- Full `.bam-*` component: `.bam-overlay`, `.bam-modal`, `.bam-head`, `.bam-members` grid, `.bam-member-card` (with selected / current / hover states), `.bam-current-block`, `.bam-note-input`, `.bam-footer`, `.bam-unassign-btn`, `.bam-cancel-btn`, `.bam-confirm-btn`
- `html.light-mode` overrides for all `.bam-*` elements

---

### 13.8 Feature — Assignment Backend Endpoints

**File:** `app/api/uploads.py`

**New helper:** `_get_batch_extra(b, workspace_id)` — resolves `uploader_name` via `User.query.get()` and fetches the latest `Assignment` for the batch, returning both fields merged into each batch dict in `api_uploads`.

**New route:** `POST/DELETE /api/workspaces/<id>/projects/<p>/uploads/<uid>/assign`

| Method | Action |
|--------|--------|
| `POST` | Validates `assigned_to` is a workspace member, deletes any existing assignment, creates new `Assignment` row with `total_images` from `_count_batch` |
| `DELETE` | Removes the current assignment for the batch |

---

### 13.9 Fix — Dataset Card Shows Source Batch Name

**Files:** `static/js/main.js`, `static/js/engine/canvas.js` → `_buildDatasetCard`

Added a `.upds-by-chip` line below the date/time row showing which batch the dataset was built from. CSS class `.upds-by-chip` added to `static/css/main.css`.

---

### 13.10 Fix — Removed Class Pills from Batch Cards

**Files:** `static/js/main.js`, `static/js/engine/canvas.js` → `_buildBatchCard`

Removed the entire `uhp-classes-row` block (class name pills rendered from annotation metadata). The Active Work cards no longer show class labels — they were cluttering the card and duplicating information available elsewhere.

---

### 13. Files Changed — Phase 3

| File | Change |
|------|--------|
| `app/api/uploads.py` | Added `_get_batch_extra()` · added `api_assign_batch` route · removed `dest.unlink()` for duplicate images · added `img_dir` guard in `api_batch_media` |
| `static/js/main.js` | `_buildBatchCard` — uploader/assignment chips, Assign button, status badge, removed class pills · `_showAssignModal` — new assignment overlay modal · `startExtractFrames` — refresh batch cards after extraction · `_handleFilesDrop` — progress bar during raw upload · `_buildDatasetCard` — source batch name chip |
| `static/js/engine/canvas.js` | Same changes as `main.js` (canvas.js is the engine copy of the same class) |
| `static/css/main.css` | Added `uhp-meta-row/chip`, `uhp-btn.assign/reassign`, full `bam-*` modal component, `upds-by-chip`, `html.light-mode` overrides for `udr-*` and `bam-*`, light-mode overrides for new chip classes |














CREATE TABLE images (
    id                   INTEGER PRIMARY KEY,

    -- Project identity (no projects table in DB — uses workspace_id + name string)
    workspace_id         INTEGER  NOT NULL,
    project              VARCHAR(200) NOT NULL,
    batch_id             INTEGER  REFERENCES upload_batches(id),

    -- File location (NEVER changes)
    filename             VARCHAR(500),
    rel_path             TEXT,

    -- Stage
    status               VARCHAR(20) DEFAULT 'active',   -- 'active' | 'in_dataset'
    split                VARCHAR(10),                    -- 'train' | 'val' | 'test'

    -- Annotation state
    is_annotated         BOOLEAN DEFAULT 0,
    is_null              BOOLEAN DEFAULT 0,              -- empty .txt = background image

    -- Who did what + when
    uploaded_by          INTEGER REFERENCES users(id),
    uploaded_at          DATETIME,
    annotated_by         INTEGER REFERENCES users(id),
    annotated_at         DATETIME,
    reviewed_by          INTEGER REFERENCES users(id),
    reviewed_at          DATETIME,
    added_to_dataset_at  DATETIME,                       -- ← just added ✅
    assigned_to          INTEGER REFERENCES users(id)
);
