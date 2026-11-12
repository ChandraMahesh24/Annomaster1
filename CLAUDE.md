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

`requirements.txt` lists every third-party package the code imports (checked
2026-11-12 against the imports and this machine's versions). Non-obvious entries:
`clip` is **OpenAI's CLIP from GitHub** (not on PyPI) and is required by SAM3 for
both text and box prompts; `opencv-python` is required (AI Annotate decodes with
cv2); `timm` is optional (DINOv2 judge, falls back to SAM3); `torch` installs the
CPU build — the GPU build is a separate command in the file's comments.

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

**SAM3 is the only engine.** YOLOE and YOLO-World were removed on request (the
`ENGINES` registry keeps its shape, so adding one back is a data change). Ignore
any older notes that call YOLOE the default.

| Engine | Prompts | Weights | Measured (2026-11, this machine) |
|---|---|---|---|
| `sam3` | text + box | user-supplied `sam3*.pt`, 3.45 GB — **not** an ultralytics asset, never auto-downloaded | text, **GPU (RTX 3050, fp16): ~0.65 s/phrase** warm, ~15 s model load on first use · CPU: ~20–30 s for 1–4 phrases |

Weights are searched through `ai_models.SEARCH_DIRS` (models/, then the repo root),
so the existing `sam3.pt` beside `run.py` is found without moving 3.45 GB. On one
frame with the same exemplar SAM3 scored 0.96 vs the old YOLOE's 0.77 — better
answers, slower runs. `speed: 'slow'` is reported by `list_engines()` **only when
running on CPU** and surfaced in the panel before the user clicks Run.

Verified text-prompt result (project `m`, `IMG_9619_MP4-0001`): "excavator" →
one box at 0.94 on the actual excavator; "tree" → ~100 raw hits, 15 above the
default 40% threshold. Broad nouns over-fire; the slider is what makes them usable.

Known gaps vs Roboflow (not yet built): no "prompt → different class name" mapping
for TEXT (a phrase reuses a project class only when the names match
case-insensitively); no apply-to-whole-job batch run (both tabs predict the image
that is open — the Box tab auto-predicts each image as it opens). The Box tab is
now a per-project example library — see "Box prompting" below.

### Text prompting — how it runs, and the rules its tests pin down

**Pipeline (`prompt_models._predict_text`).** `read_image()` decodes once (cv2
`imdecode`, so corrupt/empty files are a readable 422 and grayscale/RGBA/16-bit
become 3-channel) → `predictor.set_image()` runs the backbone **once** →
phrases go through `_boxes_only()` (boxes, no masks) **one phrase per pass**
(`PHRASE_BATCH` = 1) → `reset_image()`. Box mode still uses the old single
`predictor(source=…, bboxes=…)` call.

> ⚠️ **Never send many phrases in one forward pass.** SAM3's memory grows steeply
> per phrase: 25 at once tried to allocate **13.7 GB** on CPU, and 4 at once fills a
> 6 GB GPU. One per pass keeps the peak flat and is fastest — the backbone still
> runs only once per image.

- **`_run_lock` serialises all SAM3 inference.** The predictor holds per-image
  state (`features`, its last text classes); two interleaved requests would mix one
  image's features with another's prompt.
- **Input rules (`clean_phrases`)** — errors, never silent truncation: a list or a
  comma-separated string is accepted; dict / nested list → 422; > `MAX_PHRASES`
  (20) → 422; a phrase > `MAX_PHRASE_LEN` (64) → 422; whitespace collapsed;
  case-insensitive de-dup.
- **`ai_annotate._resolve_image()` guards BOTH `/ai/predict` and `/ai/prompt`.**
  Previously `project_dir / rel_path` accepted `../..` and, on Windows, an absolute
  `D:/…` path (which *replaces* the base) — a request could run a model on any
  image on disk. It now requires a relative path that resolves inside the project,
  with an extension in `media.ALLOWED_IMG`. Other endpoints (annotations, media)
  still use the raw join — worth the same fix.
- Bad `conf`/`iou` → 400 (was a 500); non-JSON body → 400 (was Flask's 415).
- **Browser (`prompt-annotate.js`):**
  - **New classes are POSTed to `/classes` before any box uses them**
    (`_ensureClasses`). They used to be pushed only into `state.classes`, so after
    a reload the saved boxes pointed at a class the project didn't have. A class the
    server refuses → its predictions are dropped with an error toast.
  - **AI Annotate suggestions are TRANSIENT (user's choice, 2026-11-12, "like
    Roboflow").** Every box `_toBox` makes carries `_transient: true`, and
    `Boxes.serialize` skips undecided transient suggestions — so they are NEVER
    written to the sidecar. Leave the image → gone; come back → a FRESH
    prediction (auto-predict now runs in BOTH tabs: Box from the library, Text from
    the typed phrases; the "Predict automatically" toggle sits above the slider);
    close the panel → `close()` removes them from the canvas. Accepting
    (→ confirmed) and rejecting (→ rejected) are decisions and ARE saved; a
    rejection still blocks re-suggesting. Suggestions from elsewhere (Smart Detect
    review mode) are not transient and still persist as before.
  - **A run belongs to the image it started on.** If the user left that image
    while it ran, the result is DROPPED (not painted here, not saved there); the
    image that is now open is predicted when the run ends (`_autoPending`).
    History: results used to be saved to the left image via `_applyToOtherImage`
    on a 1e9 virtual canvas — removed with the transient change. **Closing the
    panel mid-run = cancel.**
  - 2026-11-12: the 9 old unapproved suggestions persisted in project `m`
    before this change (5 sidecars, all AI Annotate) were deleted at the user's
    request; backup in that session's scratchpad (`old_suggestions_backup/`).
  - The Run button shows a live `Running… N s` counter; a non-JSON reply (proxy
    502 page) shows "unexpected response (HTTP 502)" instead of a JSON parse error.
  - Debug "it shows nothing" from the **audit log** first: `ai.prompt` rows carry the
    image, labels and `count`; the `annotation.save` rows around them (by
    `ip_address`) show where the user was when the answer arrived.

**Testing it without a browser or Node.** There is no Node on this machine;
headless Edge runs the real JS instead:
`msedge --headless=new --virtual-time-budget=15000 --dump-dom file:///…/test.html`,
where the page inlines `main.js`'s `Boxes` slice (+ `app._convertBboxes`) +
`prompt-annotate.js` through `new Function(...stubNames, src)` with stubbed
`document`/`state`/`app`/`fetch`, and writes results into a `<pre id="out">`.
Backend cases go through `app.test_client()` with `generate_token(1)`; model runs
are ~20 s each on CPU, so run that suite in the background and write results to a
file. For true end-to-end, drive the real annotate page over CDP
(`msedge --remote-debugging-port`, `websocket-client` installed to a scratch
`--target` dir, cookie `token` + `localStorage.am_token`) against a second server
on another port.

> ⚠️ **End-to-end tests write into the real `workspace/`** (auto-save writes
> sidecars). The user labels on the same project in parallel. Clean up ONLY the
> exact files your test created — a time-window `find -newermt … -delete` once
> wiped the user's own pending suggestions.

> ⚠️ **SAM3 + OpenAI `clip` = "'SimpleTokenizer' object is not callable".** ultralytics
> builds SAM3's text encoder with `clip.simple_tokenizer.SimpleTokenizer()` and then
> *calls* it, which only works with **their** CLIP fork. With OpenAI's `clip` (what is
> installed here) it dies inside the forward pass — for BOTH prompt types, since a box
> prompt still encodes the pseudo-concept `"visual"`.
> `prompt_models._ensure_clip_tokenizer_callable()` bridges it by teaching the class to
> delegate to `clip.tokenize`, guarded so installing the fork later is a no-op. Don't
> "clean up" that shim without checking which `clip` is on the machine.

- SAM3's text encoder lives **inside** the checkpoint — no separate encoder
  download. `list_engines()` reports `installed` per engine so the UI can explain a
  missing checkpoint instead of failing at prompt time.
- **The confidence slider filters, it does not re-run.** The server runs once at
  `CONF_FLOOR` (0.05) and returns everything above it; the panel keeps that list and
  re-filters locally, so "higher confidence = fewer predictions" responds per tick
  where a re-run costs ~20 s on CPU.
- **Raising the threshold is a removal, and that rule is narrow.** A box may be
  withdrawn only if it is still `suggested` *and* carries `_prun` — the session-only
  tag saying this panel added it in this session. `_prun` is deliberately never
  serialised, so after a reload the panel no longer claims those boxes. **An
  accepted box is never withdrawn**: accepting is a human decision and a slider must
  not reverse one.
- **Exemplars are prompts, not annotations.** `state.promptBoxes` + canvas mode
  `'prompt'`; never serialised, never exported, never counted as objects.
  `_onMouseUp` checks for prompt mode *before* the normal draw path so no class
  popup, history entry or auto-save can see them. On the Box tab, every on-screen
  exemplar is a SAVED library example of the current image (`exId`, `tag`,
  `positive`); accent = "this is", `--danger` = "not this" (`ThemeColors.danger`).
- **Do not monkey-patch `app.loadImage` again.** Smart Detect already wraps it;
  a second wrapper makes effect order depend on script load order. Register with
  `app.onImageLoaded(fn)`. It fires from BOTH load paths: `_applyPendingBboxes()`
  (annotations arrived first) and the "Case B" branch at the end of `loadImage`
  (image arrived first — the usual case for a cached image). ⚠️ Until 2026-11-12
  only the first fired, so AI Annotate silently missed most image changes; found
  only by the real-browser end-to-end test.
- With box prompts and no text, SAM3 labels hits as the generic concept `"visual"`,
  so `prompt_models` relabels them from the exemplars the user drew. SAM3 wants
  `imgsz=1008` (72 × its stride of 14).
- **First prompt after every server (re)start is slow** (~15–22 s on the GPU): the
  3.4 GB SAM3 checkpoint loads lazily on first use, and `debug=True`'s reloader
  restarts the server on each code change. Later prompts are ~0.65 s. A background
  warm-up in `run.py` was tried and **rolled back by the user** — don't re-add it
  without asking. If it comes back: warm only the reloader *child*
  (`WERKZEUG_RUN_MAIN == 'true'`), or the 6 GB GPU holds two copies.
- Leaving an image with unreviewed **AI Annotate** suggestions DISCARDS them
  (transient, see above) — the user asked for Roboflow behaviour after seeing old
  suggestions reappear. Smart Detect review-mode suggestions still persist in the
  sidecar until accepted (Enter / Shift+Enter) or rejected (Delete / Shift+Delete).
  Never exported either way.

### Box prompting — a per-project example library (Roboflow-style), BUILT 2026-11-12

**What the user does:** Box tab → **This is / Not this** → **Draw example box**
→ drag around one → **the same class popup annotation uses** opens → pick the
class (or **📥 Use my boxes** = this image's CONFIRMED boxes become examples, each
with its own class). Repeat mode skips the popup and reuses the last class, as
for annotation. Implementation: main.js `_onMouseUp` prompt branch builds the
box with `_prompt: true` and calls `_showClassPopup`; `_confirmPopup` routes a
`_prompt` box to `_commitPromptBox(box, cls)` (→ `state.promptBoxes` with `cls`
→ `_onPromptBoxesChanged` saves it) **before** the annotation branches, so an
example never reaches `state.bboxes`, history or auto-save; `_deleteFromPopup`
and Escape just discard it. The panel no longer requires a pre-selected class.

**Examples last ONE panel session (user's choice, 2026-11-12).** While the panel
is open they predict EVERY image: each image is auto-predicted as it opens
(toggle, persisted as `settings.ai_prompt.auto`, default on), and adding an
example re-predicts the current image at once. **Closing the panel clears the
library** — `close()` sends `DELETE /ai/examples {all:true}`, which empties
`prompt_examples.json` and calls `prompt_models.clear_example_cache()` to free
the encoded examples from RAM/VRAM — so old classes from an earlier task are
never suggested again and nothing accumulates. Suggestions already placed on
images are kept. A page reload WITHOUT closing the panel keeps the library (it
is still on disk). The file is shared per project, so closing clears it for
every user of that project. The panel lists examples per class with remove
buttons; the eraser removes the current image's. Results are ordinary
suggestions (sidecar, slider, review, confirmed-only export) — nothing new in
the lifecycle.

**Why this design** — measured on project `m`, whose `1_staff` (3,445 boxes) vs
`customer` (2,245) over 1,251 frames of `job_2026-11-11_15-26-09_954` can't be
described by a word (read-only experiments; 8–10 unseen frames):

| Approach | People found | Right class (thr 0.6) |
|---|---|---|
| Paste example crops into a strip under the target, box-prompt the crops | 38 % (thr 0.2) | P 0.13–0.20 ❌ |
| Text "person" + fingerprint class | 49 % | R 0.35 P 0.11 |
| **Example tokens encoded on their own image, reused on the target + fingerprint class** (shipped) | **92–95 %** | **R 0.78 P 0.53** (6 example frames); R 0.59 P 0.42 with 3 |
| Same, one grounding pass per class | 95–97 % | R 0.78 P 0.48 — lower precision, N× cost |

Staff-vs-customer on the TRUE boxes: 0.76 (3 example frames) → 0.86 (6): more
examples, better classes. Precision is held down mostly by people the user
doesn't label (mall corridor); "Not this" examples are the remedy.

**The "which class?" judge is DINOv2-small (since 2026-11-12), SAM3 still FINDS.**
SAM3's features are tuned for boundaries, not "does this person look like that
one". Measured on 8 other unseen frames (judge alone on true boxes, 3 → 6
example frames): SAM3 fingerprint 0.48 → 0.61; **DINOv2-small, squashed 224
crop 0.65 → 0.80**; small letterbox 0.61 → 0.76; base squash 0.80 → 0.85;
base letterbox 0.67 → 0.80. Full pipeline at thr 0.6 (what users see): SAM3
judge R 0.54–0.57 P 0.38–0.41 vs **DINOv2-small squash R 0.70–0.72 P 0.50–0.51**
— the best; base was lower in the full pipeline and 3× slower. GPU cost: ~0.85
s/image vs 0.68 s, same 3.17 GB peak VRAM; CPU: +42 ms per judged box.
- `prompt_models.appearance_backend()` → `'dinov2'` | `'sam3'`
  (`AI_APPEARANCE` env, default dinov2). `_dino_fingerprints` crops each box,
  resizes to 224², runs timm `vit_small_patch14_dinov2.lvd142m` (created with
  `img_size=224` — its default is 518 and a 224 input asserts otherwise).
  Weights download once to `~/.cache/huggingface/hub` (85 MB).
- **Never errors because of DINOv2.** No `timm`, failed download, any
  non-OOM error → `_JudgeFallback` redoes the WHOLE request with the SAM3 judge
  (examples and hits must use the same judge — different vector sizes), logs
  once, and `_dino_failed` makes later requests skip it until restart. **CUDA
  OOM is re-raised instead** (transient; `devices.run` frees VRAM and retries) —
  an early version switched DINOv2 off for good on one OOM.
- The judge name is in the example cache key; only the top `MAX_JUDGED_HITS`
  (150) hits by score are judged (the tail is below any useful slider value).
- Tests (scratchpad): 7/7 judge tests (default used, `sam3` switch, broken
  model → SAM3 with results, no retry storm, no-timm, timm back); box-by-box
  the two judges disagreed on 25 of 63 hits of one frame — so a tie in a small
  aggregate is not "DINOv2 unused".

**Pieces:**
- `core/box_examples.py` — `prompt_examples.json` (path via
  `paths.prompt_examples_file`), atomic writes, `MAX_EXAMPLES` 200, box stored
  normalised xyxy + project-relative image with `/`, dedup of identical boxes.
  Examples are NEVER annotations — not in `.txt`, not in the sidecar.
- `/api/workspaces/<id>/projects/<p>/ai/examples` GET/POST/DELETE (by `ids`,
  `image`, `class_id`, or `all`); unknown class → 422; image goes through
  `_resolve_image`. `/ai/prompt` with `mode: "examples"` predicts from the library.
- `prompt_models.predict_examples` → `_encode_image_examples` (SAM3 geometry
  encoder ON THE EXAMPLE'S OWN IMAGE → prompt tokens, positives label 1 /
  negatives 0, + 4×2 ROI-aligned `backbone_fpn[1]` fingerprints; cached in memory
  per (predictor, image, mtime, boxes)) → `_ground_with_tokens` on the target
  (SAM3's `forward_grounding` re-implemented so the "visual" concept + foreign
  tokens can be fed in) → each hit takes the class of its nearest POSITIVE
  example; a nearer NEGATIVE of that class drops it. Uses ultralytics internals
  (`_prepare_geometric_prompts`, `_get_dummy_prompt`, `_encode_prompt`,
  `_run_encoder`, `_run_decoder`, `SAM2Model._prepare_backbone_features`) —
  re-test after any ultralytics upgrade. `inst.model` is None until SAM3's first
  image → `setup_model()` first.
- Cost: first use after a restart encodes each example image once (CPU: ~2.5
  min for model + 6 images; GPU: a few s); then one grounding pass per image
  (CPU ~22–40 s, GPU ~1 s).
- **Tab race (fixed):** `open()` loads settings async; applying the saved `mode`
  there overwrote a "Box prompt" click made meanwhile, so the Box tab showed while
  runs were TEXT. Saved mode is now `_savedMode`, applied only if `!_modeTouched`.
- **Library-load race (fixed):** the first panel open after a server start
  takes seconds (`/ai/prompt/engines` imports torch); an example saved meanwhile
  was wiped from the screen by the late, stale `GET /ai/examples`. Every
  save/delete bumps `_exWrites`; `_loadExamples` applies its answer only if no
  write happened while it was in flight. Found with a real-page CDP test whose
  writes are intercepted in the page (`Page.addScriptToEvaluateOnNewDocument`
  fetch stub) — the safe way to e2e-test while the user is building their
  library. Note the popup's class items react to **mousedown**, not `click()`.

Tests (scratchpad, re-creatable): API 14 checks, browser logic 37 (Edge
headless, incl. the race), and a real-page CDP end-to-end (teach on frame
`…0006`, auto-predict `…0000`/`…0009`) that snapshots and byte-restores every
file it can write. Unlabeled frames are rare in project `m` — pick a target
without confirmed boxes of the taught classes, and mind the user's saved slider
(it was 0.9 on 2026-11-12), or the e2e sees no suggestions and looks broken.

## AI compute device — GPU or CPU, never an error

**`app/core/devices.py`** is the only place that decides where a model runs, for
both Smart Detect and AI Annotate. The same code must run unchanged on a GPU box, a
CPU-only box, and a GPU too small for the model.

- `devices.info()` resolves once per process: `cuda:0` if `torch.cuda.is_available()`,
  else `cpu`, with a `reason` (e.g. "torch is a CPU-only build").
- `devices.run(key, fn, reraise=…)` calls `fn(device, half)` down
  `('cuda', fp16) → ('cuda', fp32) → ('cpu', fp32)` until one succeeds. A non-memory
  failure (e.g. fp16 unsupported) is remembered per `key` so later requests skip it;
  **CUDA out-of-memory is not remembered** (it can be transient). `reraise` exceptions
  (`ModelError` — bad prompt, missing weights) are about the input and are never
  retried on another device.
- **Put the device in the cache key.** An ultralytics predictor binds its model to a
  device on first run. `prompt_models.load()` caches per `(…, device, half)` and
  evicts a GPU predictor that failed so its VRAM is freed; Smart Detect resets
  `model.predictor = None` before retrying on another device.
- Overrides in `.env`: `AI_DEVICE=auto|cpu|cuda|cuda:N`, `AI_HALF=auto|0`. Forcing
  `cuda` without one logs a warning and uses CPU.
- `/api/ai/prompt` returns `device` + `half`; `/api/ai/prompt/engines` returns
  `device`/`device_name`; the panel shows "Runs on CPU/GPU (name)".

**This machine runs AI on its GPU** (since 2026-11-11): RTX 3050 Laptop 6 GB,
driver CUDA 13.0, `torch 2.14.1+cu130` + `torchvision 0.29.1+cu130`, fp16.
Measured (1920×1080 frame, warm): SAM3 text prompt **0.65 s per phrase**
(CPU: 15–20 s), 8 phrases 1.9 s, 20 phrases 3.9 s, model load ~15 s on the
first request; two simultaneous requests queue (1.35 s); Smart Detect YOLO 0.02 s.

- **Windows Smart App Control had to be turned OFF** for this (the user did it).
  With it on, `import torch` fails: `WinError 4551 … Application Control policy
  has blocked … torch\lib\c10.dll` (CodeIntegrity event 3077 — the CUDA build's
  DLLs are unsigned; the `+cpu` wheel's are reputation-allowed). On another
  Windows machine, check `(Get-MpComputerStatus).SmartAppControlState` first.
  Uninstalling McAfee is irrelevant — SAC is Windows itself.
- Wheel pair: `torch==2.14.1+cu130` + `torchvision==0.29.1+cu130` (**no
  `0.29.2+cu130` exists**; no `cu128` for 2.14.1/cp310). Pin the `+cu130` local
  version — plain `torch==2.14.1` is already "satisfied" by `+cpu`. `pip
  download` first (1.9 GB), then install with `--no-deps` so numpy etc. stay put.
- **`PHRASE_BATCH = 1`** — measured, batching phrases never helps SAM3: on the
  6 GB card batch 4 hits 5.2 GB, WDDM spills VRAM to system RAM and 8 phrases take
  11 s vs 1.9 s; on CPU it is a wash. Peak VRAM stays at 2.75 GB.
- **`_boxes_only()` replaces `inference_features()`** for text prompts: the public
  call upsamples a full-res mask per hit (hundreds per frame) that we discard. It
  also fixes an ultralytics fp16 bug we'd otherwise inherit — its class-offset NMS
  adds `cls*7680` in half precision, which collapses every box of class ≥1 to a
  point (IoU 0/0), so **no NMS happens for phrase 2+** (186 vs 171 boxes on the
  test frame). Ours runs NMS in float32. Class 0 results are identical.
- **Stop `run.py` before swapping torch.** With the server running, pip can't
  delete loaded DLLs and leaves them in `site-packages/~orch*` (2.9 GB, plus
  "Ignoring invalid distribution -orch" warnings) — delete those afterwards.
- Revert = `pip install --no-deps --force-reinstall torch==2.14.1+cpu
  torchvision==0.29.2+cpu --index-url https://download.pytorch.org/whl/cpu`.
- Assistant sessions here are not allowed to stop the user's `run.py` (blocked as
  workload interference) — ask the user to Ctrl+C it.

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
