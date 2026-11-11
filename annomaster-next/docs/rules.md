# AnnoMaster-next — Engineering Rules

Hard rules for working in this codebase. Breaking one has caused a real bug before.

## A. Porting philosophy
1. **Behaviour is the spec; the UI is not.** The original Flask app defines what
   things must *do*. Do **not** clone its CSS/markup verbatim — the original never
   finished theming, responsiveness, fonts, or card sizing. **Redesign the UI to
   be better** and flag UI problems instead of carrying them forward.
2. Do port stages **one at a time**; each must be independently verifiable.

## B. Backend
1. **No `from __future__ import annotations`** in any module that defines FastAPI
   endpoints or dependencies. Stringised annotations break FastAPI's special-type
   detection (`Request`/`Response`/`Session` get treated as query params). It is
   fine in pure model/schema/service modules.
2. Keep the **router → service** split. Routers parse + delegate; services hold
   logic and stay HTTP-free.
3. **`core/paths.py` is the only path constructor.** Never build a
   `workspace/...` path anywhere else.
4. **Files never move.** Lifecycle changes are DB columns (`status`, `split`).
5. Duplicate detection is the single `images.md5` column — never reintroduce a
   separate per-project index DB (it drifted in the original).
6. `images.split` enum is **`train|valid|test`** (not `val`). Enforced by a DB
   `CHECK`. `workspace_id` is a real FK `ON DELETE CASCADE` on every scoped table.
7. Background work (ffmpeg, YOLO, ZIP export) = plain service fn + thin Celery
   wrapper. Use Celery **only if `redis_ping()` succeeds**, else run inline —
   never call `.delay()` blindly (it blocks reaching a broker that isn't there).
8. Release the DB write lock **before** slow work (e.g. `session.commit()` before
   ffmpeg) so a second writer doesn't hit "database is locked".

## C. Model-assisted labeling (the core invariant)
1. **A model prediction is a SUGGESTION until a human accepts it.** Every box has
   `st`: `suggested | confirmed | rejected` (absent = confirmed).
2. All state logic lives in the **`Boxes` module (`canvas/boxes.ts`)** — states,
   IoU, both reconcilers, accept/reject, serialise. Put new state logic there.
3. **Any code path where a human edits a suggestion MUST call `Boxes.accept()`.**
   Editing *is* acceptance. Miss it and the box keeps its dashed outline, keeps
   counting as pending, and — because only `confirmed` reaches `.txt` — is
   **silently never saved.** This caused a data-loss bug once.
4. Only `confirmed` boxes go to `<name>.txt`; `suggested`/`rejected` go to
   `<name>.suggestions.json`. Never let the sidecar leak into a dataset (copy by
   explicit `<stem>.txt`, never glob).
5. Both reconcilers compare against rehydrated `state.bboxes` — never gate re-runs
   on a session flag (an old `_seenPaths` Set duplicated boxes on reload).

## D. Frontend
1. **Auto-save is required behaviour.** `useAnnotate` must flush the outgoing
   image on navigation, debounce-save while editing, and flush on unmount. Do not
   remove these — without them, drawing + navigating loses work.
2. Draw mode draws (nested boxes allowed); Select mode edits; Pan mode / Space /
   middle-drag pans. Don't add a "select existing box" branch into draw mode.
3. React Query keys must be precise so a mutation invalidates exactly what changed.

## E. CSS / theming (read before touching any CSS)
1. Cascade is a contract: `tokens.css → base.css → layout.css → <page>.css →
   modes.css` (ported sheets), then `react-glue.css`, then `app.css`.
2. **Never hardcode a colour** in a component sheet — use a token. **Never write
   `var(--x, #hex)` with a colour fallback** (it pins the property to one theme).
3. On a saturated fill (accent/success/warning/danger) use **`--on-fill`** /
   `--up-on-primary` / `--up-on-secondary-container` for text — never `#fff`/`#000`
   (fills invert brightness between themes; white on a light tint is invisible).
4. **Specificity trap:** the Upload page is styled by `upload.css` under
   **`#page-upload .*` (ID selectors)**. Class-based overrides in `main.css` or
   `react-glue.css` will NOT win. Edit the sheet that actually applies.
5. The UI font is **Inter** (`--font-sans`). Don't reintroduce `'Sora'` literals.
6. Floating canvas surfaces (`.sd-bar`, `.zoom-controls`, `.draw-toolbar`) position
   relative to `--dt-toolbar-h`; use `--v2-frost` for translucent surfaces, never
   `--v2-on-brand` (that's a foreground token — using it as a background pins the
   surface white in both themes).

## F. Verification
1. **Verify to a FILE, not through a pipe.** `python … | grep`/`| tail`
   block-buffers stdout, so a late crash looks early. Write results to a temp file
   and `cat` it; wrap the body in try/except that writes the traceback.
2. Frontend: `npx tsc --noEmit && npx vite build` must pass.
3. `TestClient.delete()` takes no `json=`; use `c.request('DELETE', url, json=…)`.
4. `/health` returning 503 locally (Redis down) is the correct passing state here;
   green needs `docker compose up` elsewhere.

## G. Git / ops
- Commit or push only when asked. Branch off `main` first.
- Don't skip hooks or bypass signing unless explicitly asked.
