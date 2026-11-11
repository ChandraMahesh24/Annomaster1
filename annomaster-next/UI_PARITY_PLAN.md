# AnnoMaster-next — UI/UX Parity Plan

**Goal:** make the React port (`annomaster-next/`) look and behave **exactly like
the original Flask app**, page for page — same layout, same components, same
interactions, both dark and light themes. Not a redesign, not a simplification —
a faithful re-skin of the real UI on the new stack.

> The port's *backend + logic* are already done and verified (see `PORT_PLAN.md`
> / `PARITY.md`). This plan is **only about the front-end look & feel**, which the
> first pass got wrong (it used simplified, generic layouts). We fix that here.

---

## The core mismatch to correct

In the **original**, the whole authenticated app is essentially ONE screen —
`templates/pages/annotate.html` (3,780 lines) — a single-page app with a
**right-nav rail** (`.rn-*`) that hash-routes between six sections:

```
#upload   #annotate   #dataset   #versions   #classes   #projects
```

plus the annotator shell (`.toolbar` header · `.workspace`/`.canvas-area` ·
`.draw-toolbar` · `.right-nav` rail · `.statusbar`) and the Smart Detect bar.

Dashboard, Members and Settings are the only *separate* pages.

**The first React pass split upload/dataset/versions/classes into separate plain
routes with tab bars — wrong.** We rebuild the authenticated area as the same
single shell + right-rail + sections the original uses.

---

## Approach (how we get exact fidelity)

1. **Reuse the original CSS verbatim.** All 9 stylesheets are already copied to
   `frontend/src/theme/ported/` and imported in `main.tsx` in the original
   cascade order. We do **not** rewrite them.
2. **Match the markup.** Each React component emits the **same class names and
   DOM structure** as the original template, so the ported CSS styles it
   identically. (Convert `class`→`className`, `onclick`→`onClick`, etc.)
3. **Port the JS behaviour** from `main.js` / `static/js/features/*` into React
   (hooks + the canvas reducer we already built), preserving every interaction.
4. **Fonts + icons**: Sora + JetBrains Mono + Font Awesome 6.4 (already loaded in
   `index.html`). This alone was a big part of the missing look.
5. **Both themes** verified per page (`.light-mode` class on `<html>`, toggled by
   ThemeProvider — already wired).

**Fidelity target:** visually indistinguishable from the Flask app on every
screen; every interaction present. Where an exact pixel match needs a
browser to confirm, we note it.

---

## Page inventory → React mapping

| # | Original screen | Source (template · CSS · JS) | React target | Status |
|---|---|---|---|---|
| 1 | **Login** | `auth/login.html` (674) · inline · features/auth.js | `routes/Login.tsx` | ⬜ rebuild to match (mesh bg, glass card) |
| 2 | **Register** | `auth/register.html` (300) · inline · auth.js | `routes/Register.tsx` | ⬜ rebuild (split promo/form panel) |
| 3 | **Navbar** (shared) | `layout/navbar.html` · layout.css | `components/AppLayout.tsx` | ⬜ match `.navbar`/`.account-btn` |
| 4 | **Dashboard** | `workspace/dashboard.html` (257) · layout+dashboard+workspace.css · workspace.js, projects.js | `routes/Dashboard.tsx` | ⬜ match `.dashboard-page`/`.projects-grid`/`.project-card` |
| 5 | **Members** | `workspace/members.html` (80) · layout+workspace.css · workspace.js | `routes/Members.tsx` | ⬜ match `.members-*`/`.invite-card` |
| 6 | **Settings** | `pages/settings.html` (574) · settings.css · features/settings.js (960) | `routes/Settings.tsx` | ⬜ match `.settings-wrapper` sidebar + panels (Account/Theme/Card/Notifications) |
| 7 | **App shell** (toolbar + right-rail + statusbar) | `annotate.html` shell · main+annotate-v2.css · main.js | `routes/Workspace.tsx` (NEW shell) | ⬜ build the `.toolbar`/`.right-nav`/`.statusbar` frame |
| 8 | **§ Upload** | `annotate.html #page-upload` · upload.css · main.js `_bindUploadPage` | section in shell | ⬜ match `.up-layout` 3-column Stitch UI |
| 9 | **§ Annotate** (canvas) | `annotate.html #page-annotate` · main+annotate-v2.css · main.js engine | reuse `canvas/*` + `.draw-toolbar` | ⬜ restyle canvas shell to `.canvas-area`/`.draw-toolbar` |
| 10 | **§ Dataset** | `annotate.html #page-dataset` · main.css `.ds-*` · main.js | section | ⬜ match `.ds-*` grid + split UI |
| 11 | **§ Versions** | `annotate.html #page-versions` · main.css `.vw-*` · main.js | section | ⬜ match `.vw-*` version cards |
| 12 | **§ Classes** | `annotate.html #page-classes` · main.css `.cls-*` · main.js | section | ⬜ match `.cls-*` table |
| 13 | **§ Projects** | `annotate.html #page-projects` · main.css `.proj-*` · main.js | section | ⬜ match project grid |
| 14 | **Smart Detect bar** | `annotate.html` · annotate-v2.css `.sd-*` · main.js SmartDetect | `canvas/SmartDetect.tsx` | ⬜ restyle to `.sd-bar` compact/draggable |

Legend: ⬜ = to do (currently a simplified placeholder in React).

---

## Staged execution (one stage at a time, each build-verified, both themes)

- **U0 · Foundation** — ✅ DONE. Ported CSS wired in `main.tsx` (cascade order),
  Sora + JetBrains Mono + Font Awesome loaded, ThemeProvider toggles
  `.light-mode`. Build verified (CSS bundle 343 kB = full original design).
- **U2 · Shell** — ✅ DONE (structure). `routes/Workspace.tsx` = the annotate.html
  frame: `.toolbar.anno-header` header + `.right-nav` rail (6 `.rn-item` sections,
  hash-switched) + `.status-bar`. Six `sections/*Section.tsx` render in
  `.workspace`; `#annotate` has the canvas + `.draw-toolbar` + Smart Detect.
  Route `/w/:wid/p/:project` → this shell. tsc clean + build ✓. **Visual
  confirmation pending (`npm run dev`).** The 5 non-annotate sections are
  functional but still simplified inside — exact markup is U4–U6.
- **U1 · Auth** — ✅ DONE. Login's bespoke design ported verbatim (mesh bg,
  orbs/chips/rings, CSS 3-D cube, animated preview card, glass form) via extracted
  `login.css`; Register's split promo/form panel via `register.css`. Global
  `body`/`*` rules in both were scoped so they don't leak into the SPA. Only the
  decorative particle-canvas JS is omitted. Bridge `app.css` now one line. ✓.
- **U2 · Shell** — the `Workspace.tsx` frame: `.toolbar` header + `.right-nav`
  rail + `.statusbar`, with the six sections hash/route-switched (row 7). This is
  the structural backbone everything else hangs on.
- **U3 · Dashboard + Members + Settings** — ✅ DONE. Navbar (`.navbar`/
  `.account-btn` dropdown), Dashboard (`.dashboard-page`/`.dashboard-sidebar`/
  `.projects-grid`/`.project-card` w/ `.pcs-chip` stats), Members (`.members-*`/
  `.member-row`), Settings (`.settings-wrapper` sidebar + Profile/Theme/Security
  panels), Modal (`.modal-header/body/footer`) all rewired to the original
  markup. Bridge `app.css` trimmed to auth-only. tsc + build ✓. (Settings' other
  4 original tabs — notifications/language/layout/danger — deferred to U7.)
- **U4 · § Upload** — ✅ DONE. `UploadSection.tsx` rebuilt to the original
  3-column `#page-upload .up-layout`: Active Work (`.uhp-list` batch cards) ·
  Upload Data (`.upload-big-drop` + 4 `.upload-option-card` + `.up-prog-*`) ·
  Completed Datasets. Grid + panes styled by ported upload.css; fills the shell
  section area (upload.css already scopes `#page-upload .up-layout` height:100%). ✓.
- **U5 · § Annotate canvas** — ✅ DONE. Draw toolbar rebuilt to the original
  `.draw-toolbar` grouped structure (`.dt-group`/`.dt-group-label`/`.dt-btn-row`/
  `.dt-btn`, Draw/Edit/Class/Mark/File/AI groups + `.dt-hint-chip` +
  `.dt-btn-ai`). Smart Detect bar rewritten to the ported compact `.sd-bar`
  markup (`.sd-bar-head`/`.sd-bar-body`/`.sd-bar-foot`, model selector,
  Confidence+Overlap `.sd-range`, `.sd-approve`, `.sd-check` auto-approve,
  collapse/close). Reuses the tested reducer. Null wired. ✓.
- **U6 · § Dataset / Versions / Classes / Projects** — ✅ DONE. Classes
  (`.cls-page-header` + `.cls-add-form` + `.cls-table-head`/`.cls-row` + swatch
  palette), Dataset (`.ds-header` + `.ds-filter-bar` split pills + split stat
  cards + export pills), Versions (`.version-card` list + create dialog;
  4-step wizard condensed for now), Projects (`.proj-page-header` + `.proj-grid`
  with `.project-card`). Content sections scroll; upload keeps its grid. ✓.
- **U7 · Polish pass** — ✅ blind items DONE: shell geometry corrected
  (`.workspace` pinned to toolbar 52 / statusbar --sb-h / rail --rnav-w, and its
  3-column grid overridden to block so sections fill; rail top aligned).
  Settings' remaining tabs added (Notifications toggles, Layout compact-mode,
  Danger zone). Verified no theme-breaking hardcoded colours in components (only
  the intentional class-palette swatches). **Remaining needs a browser:** fine
  spacing/hover, the Versions 4-step wizard, and a visual both-theme sweep — a
  user punch-list from `npm run dev` drives these.

Each stage: match markup to the ported CSS → wire the behaviour → `tsc` + `vite
build` → check the classes resolve. Visual confirmation needs the dev server in a
browser (`npm run dev`), which you can drive.

---

## Current state (honest)

- ✅ Backend + all logic done & verified (`PARITY.md`).
- ✅ Original CSS copied to `frontend/src/theme/ported/` and imported; fonts +
  Font Awesome loaded; theme toggles `.light-mode`.
- ⚠️ React components still use the **first-pass simplified markup** — they won't
  pick up the ported styles until each is rewired to the original class names
  (that's stages U1–U7).
- The `frontend/src/app.css` / `theme/base.css` / `theme/tokens.css` from the
  first pass are superseded by the ported CSS and will be removed as we go.

## Decision needed before U1

Login/Register in the original are **bespoke** (login has a mesh gradient, glass
card, and a decorative 3-D cube + particle canvas; register is a split promo/form
panel). Matching them exactly is more effort than the token-driven pages.
Options when we start U1:
- **A. Pixel-match** including the decorative cube/particles (most faithful).
- **B. Match the layout + glass/mesh styling**, skip the animated cube/particles
  (95% of the look, much less code).

We'll pick this when we reach U1.
