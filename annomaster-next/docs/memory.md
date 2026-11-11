# AnnoMaster-next — Project Memory (gotchas & lessons)

Hard-won lessons. Each one cost real debugging time — don't rediscover them.

## Backend / FastAPI
- **No `from __future__ import annotations`** in endpoint/dependency modules —
  stringised annotations break FastAPI's special-type detection (`Request`,
  `Response`, `Session` become query params). Fine in model/schema/service modules.
- **`EmailStr`** needs `email_validator` (not installed) → use a regex validator.
- **`get_session` rollback-on-HTTPException** discarded a lockout increment →
  commit the counter *before* raising 401.
- **SQLite drops tzinfo** → naive/aware datetime comparison `TypeError` → normalise
  with an `ensure_aware()` helper.
- **`session.commit()` BEFORE ffmpeg.** ffmpeg extraction is slow; holding SQLite's
  single writer open makes any concurrent write hit "database is locked".
- **`register_on_disk` returns the `Image` (or `None`), not a status string** — the
  split-assignment code needs the row.
- **Celery task signatures must match the `.delay(...)` call** (extra `fmt/size`
  args crashed the enqueue path once).
- **`redis_ping()` before Celery.** `.delay()` blocks trying to reach a broker that
  isn't there. No Redis → run inline.

## Windows / env
- **`tempfile.mkstemp` leaves the fd open** → `WinError 32` on unlink. Close the fd
  immediately; ffmpeg opens the path by name anyway.
- **Python 3.10 f-strings can't contain a backslash** → hoist `re.sub(...)` out.
- **`run.py` must force UTF-8 stdout** — the Windows console is cp1252 and crashes
  on the `→`/`✓` glyphs it (and Vite) print.

## Verification
- **Verify to a FILE, not through a pipe.** `python … | grep`/`| tail` block-buffers
  stdout, so a late crash looks early. Write to a temp file, `cat` it, wrap the body
  in try/except that writes the traceback.
- **`TestClient.delete()` takes no `json=`** → `c.request('DELETE', url, json=…)`.
- **`/health` = 503 "degraded" locally is correct** (Redis down). Green needs
  `docker compose up`.
- **Register wants `username`, login wants `email`+`password`** (test scripts).

## Data model
- **`images.split` is `train|valid|test`** (not `val`), enforced by a DB `CHECK` —
  the original's Image docstring said `val`, which is wrong.
- **Duplicate detection = one `images.md5` column**, not a separate per-project
  index DB (the original's dual mirror drifted → orphan rows / phantom counts).
- **`workspace_id` FK `ON DELETE CASCADE` on every scoped table** — fixes the
  original's 1,406 orphan rows.

## Import / dataset
- A YOLO folder / ZIP carries **its own class ordering** (`data.yaml`/`classes.txt`).
  Merge those names into the project and **remap every label's class id**, or a
  source "0=person" silently becomes whatever class 0 is in the project. Coordinates
  are preserved; only the class column is rewritten.

## Frontend
- **Auto-save was entirely missing.** The `Auto` toggle existed but nothing called
  `save()`, so drawing + navigating lost work. Fixed with flush-on-nav + debounce +
  flush-on-unmount. **Do not remove these.**
- **Hit-test tie-break** must return the **last-drawn** box (reverse iteration +
  strict `<`), matching the original — not first-drawn.
- **`<img>` can't send a Bearer header** → the backend accepts `?token=`; the client
  appends it in `imageUrl()`.
- **The class popup needs the canvas transform** to be placed on the box — Canvas
  reports `view` via `onView`; without it the popup falls to the bottom of the page.

## CSS specificity (the one that ate three rounds of edits)
- **The Upload page card is styled by `upload.css` under `#page-upload .uhp-*`
  (ID selectors).** Class-based overrides in `main.css` / `react-glue.css` (0,1,0 /
  0,2,0) **lose** to that ID (1,0,1) regardless of load order. Edit the sheet that
  actually applies. `main.css`'s `.uhp-*` copy is effectively dead on that page.
- **`.uhp-btn { flex:1; min-width:80px }` + `.add-ds { flex:1 1 100% }`** made the
  footer 2–3 rows tall; sizing buttons to content fixed it.
- **Hardcoded `#fff` on `--up-secondary-container`** (a light purple tint) is
  invisible in light mode → use `--up-on-secondary-container`.

## Process / working style
- **Don't blindly clone the original UI** — it never handled theme/responsive/font/
  card sizing. Redesign and surface issues. (See the persistent user-memory note
  "improve-original-ui-dont-clone".)
- Make **small, verifiable** changes; confirm `tsc + vite build` (frontend) and a
  `TestClient` script (backend) after each.
