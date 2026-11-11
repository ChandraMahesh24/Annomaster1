# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> ## ⚠️ TWO codebases in this repo
>
> 1. **The original app** (repo root: `app/`, `static/`, `templates/`) — Flask +
>    SQLite + vanilla-JS. **In production, still the live app.** Everything below
>    this box describes it.
> 2. **`annomaster-next/`** — an in-progress **behaviour-parity port** to
>    **FastAPI + Postgres + Celery/Redis + React/Vite**. Has its own plan and
>    conventions; see **[`PORT_PLAN.md`](PORT_PLAN.md)** (the source of truth for
>    port status) and the "Port" section at the end of this file.
>
> When a request is about the running app, work in the root. Only touch
> `annomaster-next/` when the task is explicitly about the port.

## Commands

```bash
pip install -r requirements.txt
cp .env.example .env          # set SECRET_KEY and JWT_SECRET
python run.py                 # → http://localhost:5000 (debug, 0.0.0.0:5000)
```

Schema changes:

```bash
python migrate_db.py          # adds new columns/tables to an existing DB; idempotent
python migrate_public_ids.py  # one-off: adds USR-/WS- public IDs, renames ws folders
python scripts/migrate_v1_to_v2.py --owner-email you@example.com --workspace-name "My Workspace"
```

`flask-migrate` is installed and initialised but there is **no `migrations/` directory** — the
schema is created by `db.create_all()` in the app factory, and column additions are handled by
the hand-written `migrate_db.py` (raw `sqlite3` ALTER TABLE). Don't assume `flask db upgrade`
works.

**There are no tests, no linter, and no JS build step.** CSS and JS are served as static files
directly; there is nothing to compile. Verification is manual — run the app and exercise the
flow. Useful smoke check without a browser:

```bash
python -c "
from app import create_app; app=create_app(); c=app.test_client()
print(c.get('/login').status_code)
with app.app_context():
    for t in ['workspace/dashboard.html','pages/annotate.html','pages/settings.html']:
        app.jinja_env.get_template(t).render(); print(t,'OK')
"
```

External runtime dependency: **ffmpeg** must be on PATH for video frame extraction.
`ultralytics` (YOLO) powers AI Smart Detect; model weights live in `models/`.

⚠️ The auth code needs **`PyJWT`** (`import jwt` → `jwt.encode`). The unrelated PyPI package
named `jwt` installs the same module name without `encode`, and every login/register then 500s
with `module 'jwt' has no attribute 'encode'`. The global Python on this machine had `jwt 1.4.0`
installed as of 2026-11 — check `pip show PyJWT jwt` before debugging auth.

Checking the annotation lifecycle without a browser — the `Boxes` module is self-contained, so
it can be exercised directly:

```bash
node -e "
const src=require('fs').readFileSync('static/js/main.js','utf8');
const a=src.indexOf('const BoxState ='), b=src.indexOf('\n};',src.indexOf('serialize(list, W, H)'))+3;
eval(src.slice(a,b)+'; globalThis.Boxes=Boxes; globalThis.BoxState=BoxState;');
// …then assert against Boxes.reconcile / reconcileAutoSave / accept / serialize
"
```

## Architecture

Flask + SQLAlchemy + SQLite, serving server-rendered Jinja pages that boot into vanilla-JS
front-ends. No framework, no bundler, no npm.

**`app/api/` is thin, `app/core/` holds the logic.** Route handlers parse requests and delegate;
`core/` modules have no Flask dependencies except `current_app.config`. Keep that split.

**Two sources of truth, deliberately.** SQLite holds users, workspaces, membership, locks, audit
and batch metadata. The **filesystem** holds all image and annotation data, in a layout that is
load-bearing — `app/core/paths.py` is the only place allowed to construct those paths, and its
docstring documents the layout. `core/yolo.py` reads/writes the `.txt` label files. Annotations
are *not* in the database; a label file's location is derived from its image path by swapping
`images/` → `labels/` (`paths.label_path_for_image`).

```
workspace/<WS-XXXXXX>/projects/<project>/
  Active_Work/job_<DATETIME>/{images,labels}/     ← work in progress
  Completed_Datasets/job_<DATETIME>/{train,valid,test}/{images,labels}/
  Versions/<name>/                                 ← immutable snapshots + data.yaml
  project.json  versions.json  _uploads.json
```

**Auth is JWT, checked twice.** `app/utils/security.py` reads the token from the
`Authorization: Bearer` header *or* a `token` cookie. `@login_required` sets `g.current_user`;
`@workspace_role_required('owner','editor')` stacks *after* it and sets `g.member_role`, reading
`workspace_id` from URL kwargs → JSON body → query string. HTML page routes in
`app/__init__.py::_register_page_routes` do their own server-side redirect to `/login`, and the
front-end repeats the check client-side. Roles are owner / editor / viewer (matrix in README).

**SQLite is hardened at connect time** (`_setup_sqlite_pragmas`): `foreign_keys=ON` (off by
default in SQLite), `journal_mode=WAL`, `busy_timeout=5000`. Don't remove these — FK constraints
in the models rely on the first.

Objects carry both an integer `id` (FK joins) and a human-readable `public_id`
(`USR-7K3M9P`, `WS-847291`) from `app/utils/id_gen.py`. A workspace's `folder_name` is its
`public_id` and maps directly to a directory on disk; the app factory logs a warning on startup
for workspaces whose folder is missing.

### Front-end

**`templates/pages/annotate.html` is a single-page app.** Sections are hash-routed —
`#upload`, `#dataset`, `#versions`, `#classes`, `#annotate`, `#projects` — dispatched through
`showPage()` in `main.js`. `/pages/annotate?...#upload` and `#dataset` are the *same document*,
so a change there affects all of them. `templates/pages/{classes,dataset,versions}.html` are
3-line redirect stubs into this page, not real templates.

**⚠️ `static/js/engine/canvas.js` is DEAD CODE — nothing loads it.** The live annotation engine
is `static/js/main.js` (~7.8k lines), which contains its own copy of the same drawing code.
`canvas.js` is a stale reference copy kept from an earlier refactor. Editing it has no effect
on the running app. Verify with `grep -rn 'engine/canvas.js' templates/` before touching it.

There is **no Jinja base template**; each page is a standalone `<html>` document that
`{% include 'layout/navbar.html' %}`. A change to `<head>` must be applied to each page.

`layout/navbar.html` carries more than the `<nav>`: the inline `AccountSettings`
script (logout, the off-canvas sidebar drawer, the account-dropdown toggle) is defined
there and every page depends on it. A page that supplies its own chrome sets
`{% set hide_navbar = true %}` *before* the include — that suppresses only the `<nav>`
markup and keeps the script. `workspace/dashboard.html` does this: its redesign
(`design_handoff_dashboard_redesign/`) replaces the top navbar with a 252px rail plus
its own top bar, and re-uses the `.account-btn` / `.account-dropdown` IDs so that
script keeps driving the menu unchanged. Don't delete the include to remove the navbar.

**`templates/auth/{login,register}.html` are bespoke standalone pages** (the "Sign In 3D"
design handoff): a three.js particle planet / data field behind a glass card. Both pull
their styles from **`static/css/auth-3d.css`** and the scene + theme chip from
**`static/js/features/auth-scene.js`** (an ES module; it expects `#scene`, `#vignette`,
`#mode-btn`, `#theme-btn`/`#theme-label`, optional `#point-label`). Change those shared
files, not per-page copies. Register posts only `username/email/password`; its `MIN_PW`
must match the server's 8-char check in `api/auth.py::register`. Notes:
- three.js is loaded by dynamic `import()` from unpkg, **pinned to `three@0.184.0`** — there
  is no npm here. If the import or WebGL fails, the CSS glow washes remain as the backdrop
  and the form still works; the scene is decoration only.
- The Light/Dark chip calls `ThemeEngine.setThemeMode()` and writes `am_theme_mode` — the
  same key as Settings — so it changes the app-wide theme. A `MutationObserver` on
  `<html class>` repaints the scene. The Planet/Data-field choice is `am_login_scene`.
- Login logic is unchanged: `POST /api/auth/login` → `am_token` in local + session storage →
  redirect `/`. Google/GitHub/SSO are placeholders (no endpoints exist), and the
  "Keep me signed in" checkbox is not sent — the API has no remember-me.
- **Forgot password** = `templates/auth/forgot_password.html` (one page; `?token=` switches it
  to "choose a new password") + `/api/auth/forgot-password`, `/reset-password/check`,
  `/reset-password`; logic in **`app/core/password_reset.py`**. Tokens are *stateless*: an
  itsdangerous signature over `{uid, sha256(password_hash)[:16]}`, so they expire
  (`RESET_TOKEN_MINUTES`, 30) and are single-use with **no table or migration** — changing the
  password kills every outstanding link. The request endpoint answers identically for unknown
  emails (no account enumeration) and sends on a thread so timing doesn't leak either. With
  no `MAIL_SERVER` set, the link is **logged** (`WARNING`, `app.core.password_reset`) rather than
  emailed. Set `APP_BASE_URL` in production, else links use the request `Host` header.
  A reset does not revoke existing JWTs (they carry no password stamp).
- Stats, compliance badges and footer links are design copy, not real data.

**Draw mode draws; Select mode edits.** In `bbox` mode a drag anywhere starts a new box —
including *inside* an existing one, so nested annotations work. Only the resize handles of the
box you just drew stay active. The class/delete popup opens in `edit` mode only. Both
behaviours used to leak across modes, which made nested boxes impossible to draw and popped an
edit panel mid-draw; don't reintroduce a "select existing box" branch into `bbox` mode.

## Model-assisted labeling — the core invariant

**A model prediction is a SUGGESTION, never an annotation, until a human accepts it.**

Every box carries `st`: `suggested` | `confirmed` | `rejected` (absent = `confirmed`, which is
how pre-feature annotations stay valid). All the rules live in the **`Boxes` module in
`main.js`** — states, IoU, both reconcilers, accept/reject, and the wire serialiser. Put new
state logic there rather than inline at a call site.

Storage splits by state, and this is what makes exports safe:

```
labels/<name>.txt                 CONFIRMED only  → ground truth
labels/<name>.suggestions.json    suggested + rejected + confidence  (app/core/suggestions.py)
```

Three properties fall out of that split, with **no exporter changes**: exports contain only
human-confirmed work; `Image.is_annotated` (via `is_valid_annotation_file`) can't flip on
detections alone; and rejected boxes survive a reload so a re-run won't re-suggest them.
`core/versions.py` and `core/datasets.py` copy labels by explicit `<stem>.txt`, never by
globbing, so the sidecar cannot leak into a dataset.

> ⚠️ **Any code path where a human edits a suggestion MUST call `Boxes.accept(box)`.**
> Editing *is* acceptance. Miss it and the box keeps its dashed outline, keeps counting as
> pending, and — because only `confirmed` reaches the `.txt` — **is silently never saved**.
> This has already been the cause of one data-loss bug. Current paths: the class popup's
> `_editId` branch, the class list/sidebar, both properties-panel handlers, and drag/resize
> in `_onMouseUp`.

Two reconcilers, deliberately different — both match on same-class + IoU:

| Detection overlaps | `reconcile` (Review) | `reconcileAutoSave` (Auto-approve) |
|---|---|---|
| a `confirmed` box | **discard** — never touch human work | **replace coordinates in place** |
| a `suggested` box | refresh coords/confidence | replace + promote |
| a `rejected` box | skip | skip |
| nothing | add as `suggested` | add as `confirmed` |

Both compare against `state.bboxes` — rehydrated from disk on every frame load — so
idempotency survives reloads and navigation. **Never** gate re-runs on a session flag; an
earlier `_seenPaths` Set did exactly that and reset on reload, which is what duplicated boxes.
Note both reconcilers **mutate in place** (the boxes are live canvas state), which matters when
writing tests.

## Smart Detect

Model discovery, validation, class introspection and instance caching live in
**`app/core/ai_models.py`**; `app/api/ai_annotate.py` is the HTTP surface.

- `models/` is re-scanned **per request** — a `.pt` dropped in while the server runs appears on
  refresh. Never cache the list at boot.
- **Loaded YOLO instances are cached** keyed by `(path, mtime, size)`. `api_ai_predict`
  previously constructed `YOLO()` on every request — ~8 s per detection on a 5 MB checkpoint.
  The mtime in the key means re-training under the same filename still reloads.
- Invalid weights raise `ModelError` → **HTTP 422 with a readable message**, never a bare 500.
  `resolve_path()` strips directory components, so a model name can't escape `models/`.
- Per-project settings (`model`, `conf`, `iou`, `mode`) persist in `project.json` under
  `settings.ai`. Different projects target different object sets, so this is per-project, not
  global or localStorage.
- Auto-approve mode writes ground truth with no human in the loop, so every run is audit-logged
  as `ai.autosave`.
- **There is no Detect button** — detection auto-runs on image load in both modes (safe because
  reconcile is idempotent). The `➤` button is a manual re-run after changing model/thresholds.
- The Smart Detect bar is draggable and collapsible; position is stored as a **viewport
  fraction** (not pixels) so it can't end up off-screen on a smaller display.

## AI Annotate — prompted labeling (text + box prompting)

The second AI tool in the drawing toolbar (group **Prompt**, `#promptAnnotateBtn` →
floating `#paBar`). Smart Detect runs a fixed detector and the weights decide the
classes; this asks for objects the *user* names — as words ("forklift"), or as one
example box drawn on the frame. Engines live in **`app/core/prompt_models.py`**,
HTTP in the second half of `app/api/ai_annotate.py`, UI in
**`static/js/features/prompt-annotate.js`** (the first annotate-page feature kept
out of the template — Smart Detect's ~1000 inline lines are why).

**It adds no second annotation lifecycle.** `/ai/prompt` returns the *same* wire
shape as `/ai/predict`, so predictions commit through `Boxes.reconcile()` and land
as suggestions with the same sidecar, review and confirmed-only-export guarantees.
Everything in "Model-assisted labeling" above applies unchanged.

| Engine | Prompts | Weights | Measured on this CPU-only box |
|---|---|---|---|
| `yoloe` (default) | text + box | `yoloe-11s-seg.pt`, 28 MB, auto-downloaded | ~5 s cold, **~1.6 s** warm |
| `world` | text only | `yolov8s-worldv2.pt`, 26 MB | untested (needs its CLIP download) |
| `sam3` | text + box | user-supplied `sam3*.pt`, 3.45 GB — **not** an ultralytics asset | **~3 min/image**, but far more accurate |

Weights are searched through `ai_models.SEARCH_DIRS` (models/, then the repo root),
so the existing `sam3.pt` beside `run.py` is found without moving 3.45 GB. Same
verified numbers on one frame with the same exemplar: YOLOE 0.77, SAM3 0.96 — SAM3
is the better answer and the worse experience, which is why `speed: 'slow'` is in
the registry and surfaced in the panel before the user clicks Run.

> ⚠️ **SAM3 + OpenAI `clip` = "'SimpleTokenizer' object is not callable".** ultralytics
> builds SAM3's text encoder with `clip.simple_tokenizer.SimpleTokenizer()` and then
> *calls* it, which only works with **their** CLIP fork. With OpenAI's `clip` (what is
> installed here) it dies inside the forward pass — for BOTH prompt types, since a box
> prompt still encodes the pseudo-concept `"visual"`.
> `prompt_models._ensure_clip_tokenizer_callable()` bridges it by teaching the class to
> delegate to `clip.tokenize`, guarded so installing the fork later is a no-op. Don't
> "clean up" that shim without checking which `clip` is on the machine.

- **Text prompting is the expensive path, box prompting is not.** YOLOE text needs
  a ~600 MB MobileCLIP encoder (YOLO-World: ~340 MB CLIP ViT-B/32) downloaded once;
  box prompting derives its embedding from the drawn region and needs no encoder at
  all. `list_engines()` reports `installed` per engine so the UI can warn before a
  first run instead of parking on a spinner. Auto-downloaded weights are gitignored;
  weights a project ships deliberately are not.
- **The confidence slider filters, it does not re-run.** The server runs once at
  `CONF_FLOOR` (0.05) and returns everything above it; the panel keeps that list and
  re-filters locally, so "higher confidence = fewer predictions" responds per tick
  where a re-run costs seconds on CPU (measured: ~5 s cold, ~1.6 s warm).
- **Raising the threshold is a removal, and that rule is narrow.** A box may be
  withdrawn only if it is still `suggested` *and* carries `_prun` — the session-only
  tag saying this panel added it in this session. `_prun` is deliberately never
  serialised, so after a reload the panel no longer claims those boxes. **An
  accepted box is never withdrawn**: accepting is a human decision and a slider must
  not reverse one.
- **Exemplars are prompts, not annotations.** `state.promptBoxes` + canvas mode
  `'prompt'`; drawn in accent, never serialised, never exported, never counted as
  objects. `_onMouseUp` checks for prompt mode *before* the normal draw path so no
  class popup, history entry or auto-save can see them.
- **Do not monkey-patch `app.loadImage` again.** Smart Detect already wraps it;
  a second wrapper makes effect order depend on script load order. Register with
  `app.onImageLoaded(fn)`, fired from `_applyPendingBboxes()` where both load paths
  converge.
- YOLOE's visual-prompt mode names its classes `object0…objectN` in the order the
  exemplar labels were first seen, so `prompt_models` remaps them back to the labels
  the user actually drew. SAM3 wants `imgsz=1008` (72 × its stride of 14).

## Theming — read before touching any CSS

The design-token layer is the single source of truth and the cascade order is a **contract**:

```
tokens.css → base.css → layout.css → <page>.css → modes.css
```

- **`tokens.css`** — every colour, type, space, radius, motion and z-index token. Dark and light
  are both *derived* themes (`:root` = dark, `:root.light-mode` = light); neither is baked into
  a component sheet. Adding a theme = adding one block here.
- **`base.css`** — reset, root typography, `:focus-visible` rings, scrollbars, and the shared
  primitives (`.btn`, `.form-*`, `.card`, `.modal`, `.badge`).
- **`modes.css`** — `.custom-mode` (user-picked colours from Settings) and `.compact-mode`
  component rules. Extracted from the deleted `theme.css`; **`custom-mode` is a real
  user-facing feature**, don't assume these rules are dead.

Rules for changes:

- **Never hardcode a colour in a component sheet.** Use a token. The app previously had
  *seven* competing palettes (`main.css`, `layout.css`, `auth.css`, two inline `<style>` blocks,
  `--up-*`, `--v2-*`) and light mode was a 1,742-line override sheet with 573 `!important`
  declarations. That is what was removed; don't reintroduce it.
- **Never write `var(--x, #somehex)` with a colour fallback.** The fallback silently pins the
  property to one theme when the variable is empty — a past source of light-mode breakage.
- `--on-fill` is the foreground for text on any *saturated* fill (accent, success, warning,
  danger). It is near-black on dark and white on light, because those fills invert brightness
  between themes. Never hardcode `#000`/`#fff` there. `--accent-ink` is an alias kept for
  compatibility.
- `--ink-a02…a30` is a contrast-overlay ramp (white on dark, near-black on light) for hairline
  borders and hover fills. `--accent-a04…a40` is the same idea for accent washes.
- Use only these breakpoints: **639px** (mobile), **1023px** (tablet), **1024px+** (laptop),
  **1440px+** (desktop), **1920px+** (ultra-wide). Values that vary by viewport belong in
  `tokens.css` so components stay breakpoint-free.

**Compatibility alias layers.** `upload.css` (`--up-*`) and `annotate-v2.css` (`--v2-*`) each
keep a private token namespace that now *aliases* the semantic tokens. This is what gives those
sheets theming without rewriting ~1,500 rules. Change the alias block at the top of each file,
not the rules below it.

> ⚠️ **`--v2-on-brand` is a FOREGROUND token** (`rgba(255,255,255,.92)`, the text colour for the
> permanently-dark `.rn-*` nav rail). Using it as a `background` pins that surface to white in
> **both** themes. A bulk find-replace once did this to five floating surfaces
> (`.draw-toolbar`, `.zoom-controls`, `.img-nav-bar`, `.atd-pill`, `.draw-dim-badge`) and the
> bug shipped unnoticed. For a translucent floating surface use **`--v2-frost`**, which is
> derived from `--surface` and follows the theme.

**Floating surfaces over the canvas must not collide.** `--dt-toolbar-h` (in `tokens.css`, 46px,
32px once button captions hide below 1100px) is the single source for the drawing toolbar's
height; the Smart Detect bar positions itself at `calc(var(--dt-toolbar-h) + 20px)`. Both were
previously `top:12–14px; left:50%` — the same spot — so one covered the other. Position any new
floating panel relative to this token rather than adding another magic number.

`annotate-v2.css` still carries ~850 `!important` declarations. They are structural — the sheet
is an override layer on top of `main.css` — and the values they carry are tokens, so theming
works regardless. Removing them means merging the two sheets; don't start that casually.

Deliberately **not** themed, do not "fix" these:
- `CLASS_PALETTE` in `main.js` — identifies annotation classes; theming it would make a saved
  box appear to change class when the theme is switched.
- The `.rn-*` left nav rail (`--v2-brand-dark`) — a fixed dark brand surface in both themes.
  Its foreground is `--v2-on-brand` / `--v2-on-brand-dim`.
- `.dark-preview` / `.light-preview` swatches in `settings.css` — they must render their own
  palette to work as a theme picker.
- The auth pages' `--lg-*` palette (`static/css/auth-3d.css`) — a brand surface whose
  colours must match its WebGL scene, which can't read CSS. It is still theme-aware: one
  block per theme, keyed on `:root.light-mode` / `:root:not(.light-mode)`. Keep colour
  literals inside those two blocks; the rules below them use only `--lg-*` names.
- Canvas resize **handles** (white fill + class-colour ring). They sit on the user's image, not
  on a themed surface, so they are theme-independent by design.

**Canvas is painted by JS, so CSS tokens can't reach it.** `main.js` has a `ThemeColors` helper
that reads live token values off `<html>` (cached; invalidated by a `MutationObserver` on the
class/style attributes). Use `ThemeColors.get()` / `ThemeColors.accentAlpha(a)` for grid,
crosshair and guide colours rather than literals.

`static/js/theme.js` runs **synchronously in `<head>` before paint** to apply the saved theme
and avoid a flash. It reads `am_theme_mode` / `am_accent_color` / `am_layout_mode` from
localStorage, falling back to scanning for per-user `am_*_<id>` keys.

Note: the CSS file list in `README.md` is stale — it predates the token refactor and names
several files that no longer exist.

## Port to FastAPI + Postgres + Celery + React (`annomaster-next/`)

A staged, behaviour-parity rewrite. **The original app is the reference spec**;
the port must match its user-facing behaviour, not redesign it. Progress and the
per-stage plan live in **[`PORT_PLAN.md`](PORT_PLAN.md)** — read it first, and
update its checkboxes + progress log as stages land. Do stages one at a time;
each must be independently verifiable before moving on.

Layout: `annomaster-next/{backend,frontend}` + `docker-compose.yml`.
Backend = SQLAlchemy 2.0 (typed) + Pydantic + Alembic; thin routers → `services/`
(same split as the original's `api/` vs `core/`). `app/core/paths.py` is again
the ONLY path constructor. Files still never move; annotations still live on disk
(`.txt` confirmed-only + `.suggestions.json` sidecar), NOT in Postgres.

**Status (2026-07):** Phase A done (A0 scaffold · A1 model · A2 auth · A3
workspaces+isolation), Phase B through B3 (B1 uploads · B2 annotations+locking ·
B3 Smart Detect). Next: B4 datasets/exports, then Phase C (React), D (parity).

### This machine can't run the full stack — verify on SQLite
No Docker, no Postgres/Redis running, no Celery/psycopg installed (network is
flaky for `pip`/`npm`). So: the app targets Postgres, but is **verified against
SQLite** by setting `DATABASE_URL=sqlite:///…` + `WORKSPACE_ROOT=…` env vars and
running `alembic upgrade head` then a `TestClient` script. `/health` returns 503
here (both backends down) — that's the correct passing state locally; green
needs `docker compose up` elsewhere. ffmpeg and ultralytics ARE present, so video
extraction and YOLO predict were verified for real.

### Port gotchas already hit (don't rediscover these)
- **No `from __future__ import annotations` in any module defining FastAPI
  endpoints/dependencies.** Stringised annotations break FastAPI's special-type
  detection — `Request`/`Response`/`Session` get treated as query params. Fine in
  pure model/schema/service modules.
- **Verify to a FILE, not through a pipe.** `python … | grep`/`| tail`
  block-buffers stdout, so a late crash looks like an early one. Write results to
  a temp file and `cat` it; wrap the body in try/except that writes the traceback.
- `db.py` sets SQLite `busy_timeout` + `foreign_keys=ON` (mirrors the original's
  pragmas; no effect on Postgres) — needed or a second writer errors immediately.
- `workspace_id` is now a **real FK with `ON DELETE CASCADE`** on every scoped
  table — the fix for the original's 1,406 orphan rows. Enums are DB `CHECK`s.
- `images.split` enum is `train|valid|test` (the real data), NOT the `train|val|
  test` in the original's Image docstring or the port prompt's summary.
- Duplicate detection is ONE column (`images.md5`) on the central table, not a
  separate per-project index DB — the original's dual-mirror caused drift.
- `TestClient.delete()` takes no `json=`; use `c.request('DELETE', url, json=…)`.

### Related: DB-audit tooling added to the ORIGINAL app
`scripts/check_consistency.py` (bidirectional DB↔filesystem↔index drift report,
exit 1 on drift) and `scripts/backup.py` (SQLite Online-Backup-API snapshot + the
`workspace/` tree together; Windows long-path safe). The original also gained a
`/health` endpoint and enum-guard triggers + unique indexes in `migrate_db.py`.
