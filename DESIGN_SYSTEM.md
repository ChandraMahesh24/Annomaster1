# AnnoMaster design system

The single reference for how the live app (Flask + Jinja + vanilla JS, repo root)
is styled. It covers where each design decision lives, how to change it once for
every page, and the rules new pages must follow. `annomaster-next/` (the
React port) is out of scope.

**Rule for every UI change:** check `static/css/tokens.css` first. If the change
is a colour, font, size, spacing, radius, shadow or component property, make it
there or in `static/css/components.css`, not in a page sheet.
`python scripts/check_design_tokens.py` fails if styling bypasses the tokens.

---

## 1. Architecture at a glance

```
templates/layout/head_assets.html   ← every page includes this ONE <head> partial
        │  loads, in this order (the cascade contract):
        ├─ Google Fonts (Sora + JetBrains Mono) + Font Awesome 6.4
        ├─ static/css/tokens.css        ① design tokens: colour, type, space, radius,
        │                                   motion, z-index, component knobs, breakpoints
        ├─ static/css/base.css          ② reset, root typography, focus ring, scrollbars,
        │                                   .container / .scroll-x / .visually-hidden
        ├─ static/css/components.css    ③ shared components (.btn, .form-*, .card, .modal,
        │                                   .badge, .ui-table, .ui-tabs, .ui-toast …)
        ├─ page_css …                   ④ page sheets, listed by the page
        ├─ static/css/modes.css         ⑤ custom-colour + compact-density modes (always last)
        ├─ static/js/theme.js           pre-paint theme bootstrap (no flash)
        └─ static/js/core/ui.js         UI.toast / UI.confirm / UI.tabs
```

| Layer | File | Owns | Never put here |
|---|---|---|---|
| Tokens | `static/css/tokens.css` | every value: palette, type scale, spacing, radii, shadows, motion, z-index, component knobs, responsive token overrides | selectors other than `:root` / theme classes |
| Base | `static/css/base.css` | reset, `body`/`h1–h4` typography, `:focus-visible`, scrollbars, layout helpers | components |
| Components | `static/css/components.css` | reusable UI pieces, driven only by tokens | page-specific layout |
| Page | `static/css/<page>.css` | layout of one page (grids, positions) | colours, font names, raw font sizes |
| Modes | `static/css/modes.css` | Settings' *custom colours* and *compact density* | normal theme styling |
| Shell | `static/css/layout.css` | top navbar, account menu, dashboard/members page frames | — |
| JS helpers | `static/js/core/ui.js` | toast, confirm dialog, tab keyboard behaviour | page logic |

Cache-busting is automatic: `asset('css/x.css')` (a Jinja global registered in
`app/__init__.py::_register_asset_helper`) appends `?v=<file mtime>`, so an edit
reaches browsers on the next normal reload. Never hand-write `?v=` strings.

### Page inventory: who loads what

| Route | Template | `page_css` | Notes |
|---|---|---|---|
| `/login`, `/register`, `/forgot-password` | `templates/auth/*.html` | `auth-3d.css` | `no_icons`; brand palette `--lg-*` (see §3.4) |
| `/help` | `templates/pages/help.html` | `help.css` | `no_icons`; prose measure `--content-prose` |
| `/` Dashboard | `templates/workspace/dashboard.html` | `layout.css`, `workspace.css`, `dashboard.css` | own 252px rail; `--dsh-*` aliases map to tokens |
| `/workspace/<id>/members` | `templates/workspace/members.html` | `layout.css`, `workspace.css` | uses `.ui-page-title` |
| `/settings` | `templates/pages/settings.html` | `layout.css`, `settings.css` | theme panel uses `.st-*` classes |
| `/pages/annotate#upload … #projects` | `templates/pages/annotate.html` | `main.css`, `upload.css`, `annotate-v2.css`, `dataset.css`, `media-library.css`, `classes.css` | one document, six hash sections; `--up-*` / `--v2-*` alias layers; Classes uses shared table/inputs/buttons with mobile card rows |
| `/pages/upload` | redirect → `#upload` | — | `templates/pages/upload.html` is unrendered legacy |
| `/health` | JSON | — | — |

There are **no** Model training, Model deployment or Analytics pages in this app.
Don't add navigation for them until they exist.

---

## 2. Colour

### 2.1 Palette (from the existing visual identity)

The palette was already established before this pass. It was kept, not
replaced: an **electric teal** accent on near-black slate in dark mode, a
**deep green** accent on cool white in light mode, plus violet as the
secondary hue. Primitives (`--p-*`) are raw values; components never use them.

| Role (semantic token) | Dark (default) | Light |
|---|---|---|
| `--bg` page | `#07070d` | `#f7f9fb` |
| `--surface` bars, menus | `#0d0d16` | `#ffffff` |
| `--panel` inputs, wells | `#111119` | `#f2f4f6` |
| `--card` / `--card2` / `--card3` | `#16161f` / `#1c1c28` / `#242432` | `#ffffff` / `#eceef0` / `#e6e8ea` |
| `--tx` / `--tx2` / `--tx3` text | `#f0f0f8` / `#70708a` / `#36364a` | `#191c1e` / `#3c4a42` / `#6c7a71` |
| `--border` / `--border2` / `--border3` | white 6% / 10% / 15% | ink 10% / 16% / 26% |
| `--accent` primary | `#00e5b0` teal | `#006c49` green |
| `--accent-dim` hover/active | `#00b88a` | `#005236` |
| `--purple` secondary | `#a07aff` | `#6d28d9` |
| `--success` / `--warning` / `--danger` / `--info` | `#1de97a` / `#ffb020` / `#ff4060` / `#4da6ff` | `#04724d` / `#96600a` / `#ba1a1a` / `#1d4ed8` |
| `--on-fill` text on any saturated fill | `#00120c` (dark) | `#ffffff` |
| `--on-purple` text on a solid purple fill | `#16061f` | `#ffffff` |

Washes and states:

* `--accent-bg`, `--accent-glow`, and the `--accent-a04 … --accent-a40` alpha ramp
* `--success-bg/-br`, `--warning-bg/-br`, `--danger-bg/-br`, `--info-bg/-br`, `--purple-bg/-br`
* `--ink-a02 … --ink-a30`: a contrast overlay (white on dark, near-black on light)
  for hairlines and hover fills
* `--glass`, `--glass-hover`, `--overlay` (modal backdrop), `--focus-ring`
* For an alpha of any token: `color-mix(in srgb, var(--warning) 20%, transparent)`

### 2.2 How to change global colours

* **The brand accent:** edit `--p-teal-400`/`--p-teal-500` (dark) and
  `--p-green-600`/`--p-green-700` (light) in `tokens.css`. Then update the
  matching rgba values in `--accent-bg`, `--accent-glow`, `--accent-a*` and
  `--sh-accent` in both theme blocks (CSS can't derive alpha from a hex token in
  all the places these are used). Check contrast of `--on-fill` on the new accent.
* **A status colour:** edit `--p-success-d` / `--p-success-l` (etc.) and its `-bg`/`-br` washes.
* **Surfaces or text:** edit the `--p-ink-*` / `--p-snow-*` / `--p-slate-*` primitives.
* **Add a theme:** add one block `:root.<name>-mode { … }` that redefines the
  semantic tokens. Nothing else changes. `static/js/theme.js` applies the class.
* Users can also override the accent and colours at runtime in **Settings →
  Theme & Colors** (`ThemeEngine` in `theme.js` writes the same tokens on `:root`;
  the `.custom-mode` rules in `modes.css` read them).

### 2.3 Colour rules

* Component and page CSS uses semantic tokens only. `scripts/check_design_tokens.py` rejects `#hex`, `rgb()`
  and `rgba()` literals in CSS rules and inline `style=""`. The one exception is pure-black alpha
  `rgba(0,0,0,a)`, which is allowed for shadows and photo scrims.
* Never write `var(--x, #hex)`: a colour fallback silently pins one theme.
* Text on a saturated fill (accent/success/warning/danger buttons, badges,
  checkmarks) uses `--on-fill`, never `#fff`/`#000`. On a purple fill, use `--on-purple`.
* Canvas drawing can't read CSS variables. `main.js` → `ThemeColors.get()` returns
  `accent`, `grid`, `onFill`, `text`, `danger` and `font` read from the tokens.
  Use it, not literals.
* Deliberately **not** themed: `CLASS_PALETTE` (annotation class identity), canvas
  resize handles and marks drawn on photos, theme-preview swatches in Settings, and
  the auth `--lg-*` brand palette. These are fenced with `ds-allow-start: <reason>`
  comments so the guard skips them. Don't add exceptions without a reason.

### 2.4 Readable text in every theme (contrast contract, 14 Nov 2026)

Text tokens are tuned so that every theme, including a user's custom one, meets
WCAG AA (4.5:1, or 3:1 for large text) on every surface:

| Token | Use | Guarantee |
|---|---|---|
| `--tx` | primary text | highest contrast |
| `--tx2` | secondary text (subtitles, labels, descriptions) | ≥ 6:1 |
| `--tx3` | muted text (hints, timestamps) | ≥ 4.5:1 — never lower it for "subtle" text |
| `--accent-text` | accent-coloured **text** (links, active tabs, counts) | ≥ 4.5:1 on all surfaces and on `--accent-bg` |
| `--split-train/val/test-text` | split names/badges as text | same |

* **Accent as text uses `--accent-text`, accent as fill uses `--accent`.** A bright
  accent (`#00e5b0`) is a fine fill but unreadable as text on white. All 188 old
  `color: var(--accent)` text rules were moved to `--accent-text`.
* **Theme Settings can't break this.** `theme.js` recomputes the derived text
  tokens whenever the user picks a custom background/text colour or a custom
  accent: `--tx2`/`--tx3` are blended from the custom text toward the
  background only as far as contrast allows, and `--accent-text` is the picked
  accent moved toward white (dark bg) or black (light bg) just enough to reach
  4.5:1 on every surface. Fills keep the exact colour the user picked.
* A custom theme takes the base light or dark palette from its background's
  luminance via `<html class="light-mode">` **only** — never `body.light-mode`,
  which redeclares the stock light tokens and shadows the custom colours.
* JS-built markup uses tokens too: `style="color:var(--warning)"`, washes via
  `color-mix(in srgb, var(--x) 10%, transparent)`. Never hex + alpha suffix
  (`${col}22`), which can't work with a token. Readable text from an arbitrary
  token colour: `color-mix(in srgb, var(--x) 60%, var(--tx))`.
* Verified by `browser_audit.py ds-contrast` (§8).

---

## 3. Typography

### 3.1 Font families: change them in one place

| Token | Value | Used for |
|---|---|---|
| `--font-sans` | `'Sora', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif` | all UI text, and canvas labels via `ThemeColors.get().font` |
| `--font-mono` | `'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace` | IDs, counts, paths, code |

**To change the app font:** (1) edit `--font-sans` in `static/css/tokens.css`;
(2) change the family in the Google Fonts URL in
`templates/layout/head_assets.html`. No stylesheet, template or script names a
font anywhere else (the guard enforces it).

### 3.2 Size scale

Sizes are **steps**, one per pixel size the UI uses, all multiplied by one knob:

```css
--font-scale: 1;                                   /* global text-size multiplier */
--fs-8 … --fs-36, --fs-40, --fs-48, --fs-56        /* e.g. --fs-13: calc(0.8125rem * var(--font-scale)) */
```

The steps are rem-based, so they also respect the user's browser font-size setting.
The original t-shirt names remain and alias steps: `--fs-2xs` 11 · `--fs-xs` 12 ·
`--fs-sm` 13 · `--fs-md` 14 · `--fs-lg` 16 · `--fs-xl` 20 · `--fs-2xl` 24 (22 tablet, 20 mobile) ·
`--fs-3xl` 32 (28 / 24).

### 3.3 Role tokens: what a piece of text *is*

Shared components consume these, so changing one role changes that kind of text everywhere.

| Token | Default | Used by |
|---|---|---|
| `--text-page-title` | `--fs-2xl` (24) | `h1`, `.ui-page-title` |
| `--text-section-title` | `--fs-xl` (20) | `h2`, `.ui-section-title` |
| `--text-card-title` | `--fs-lg` (16) | `h3` |
| `--text-subtitle` | `--fs-md` (14) | `h4`, modal titles |
| `--text-body` | `--fs-sm` (13) | `body`, alerts, toasts |
| `--text-secondary` | `--fs-xs` (12) | captions, breadcrumbs, help text |
| `--text-label` | `--fs-2xs` (11) | `.form-label`, overlines |
| `--text-button` / `--text-button-sm` | 13 / 12 | `.btn` / `.btn-sm` |
| `--text-input` | `--fs-md` (14) | `.form-input/select/textarea` (16px on phones: iOS no-zoom) |
| `--text-table` / `--text-table-head` | 13 / 11 | `.ui-table` |
| `--text-nav` | 13 | `.ui-tab`, nav items |
| `--text-badge` | 11 | `.badge` |
| `--text-mono` | 12 | `.mono` |
| `--fw-page-title` / `--fw-heading` / `--fw-label` / `--fw-button` | 800 / 700 / 700 / 700 | the matching components |

Line heights `--lh-tight/-snug/-base`, letter spacing `--ls-tight/-snug/-wide/-wider`,
weights `--fw-normal … --fw-black`.

### 3.4 Changing sizes

* **Everything bigger or smaller:** `:root { --font-scale: 1.0625; }` in `tokens.css`.
  This is verified to reach every page; see §8. The annotation canvas labels keep their pixel size.
* **One role (e.g. all buttons):** change `--text-button`.
* **One step everywhere:** change `--fs-11` (affects every use of that step).
* In page CSS use a role token if one fits, otherwise a step. Never a raw `px`/`rem`
  font size (the guard rejects ≥8px literals; sub-8px icon glyphs are exempt).
* `scripts/tokenize_typography.py` converts stray literals back to steps (snapping
  off-scale values to the nearest step, ties down) and lists what it snapped.

---

## 4. Spacing, layout, radius, elevation, motion

### 4.1 Global knobs (one number each, every component on every page)

```css
/* static/css/tokens.css, top of the theme-independent :root block */
--font-scale:      1;      /* all text sizes                        */
--radius-scale:    1;      /* every corner radius (0 = square UI)   */
--space-scale:     1;      /* every padding / margin / gap          */
--shadow-strength: 1;      /* every shadow's opacity (0 = flat UI)  */
--motion-scale:    1;      /* every transition / animation duration */
--shadow-rgb:      0 0 0;  /* shadow colour                         */
```

How they reach everything: every literal radius, padding/margin/gap, black
shadow and duration in every stylesheet was rewritten by
`scripts/tokenize_geometry.py` to a **step token** that is multiplied by its
knob: `border-radius: var(--rad-8)` where `--rad-8: calc(8px * var(--radius-scale))`,
and `padding: var(--s-12)` where `--s-12: calc(12px * var(--space-scale))`. Shadows
become `rgb(var(--shadow-rgb) / calc(.3 * var(--shadow-strength)))` and durations
`calc(150ms * var(--motion-scale))`. The steps live in the GENERATED block at the end of
`tokens.css`; never edit it by hand. At knob value 1 the result is pixel-identical,
which was verified by an 84/84 identical snapshot diff. The named tokens below
(`--r-*`, `--sp-*`, `--dur-*`, `--sh-*`) also multiply by the knobs.

Set knobs only on `:root`: the steps are resolved there.

| Group | Tokens |
|---|---|
| Spacing (4px grid) | `--sp-1` 4 · `--sp-2` 8 · `--sp-3` 12 · `--sp-4` 16 · `--sp-5` 20 · `--sp-6` 24 · `--sp-8` 32 · `--sp-10` 40 · `--sp-12` 48 · `--sp-16` 64 (larger steps shrink on tablet/mobile, grow on ultra-wide) |
| Page frame | `--page-pad`, `--section-gap`, `--grid-gap`, `--content-max` 1280, `--content-wide` 1600, `--content-prose` 52rem |
| Shell metrics | `--nav-h` 52 · `--tb-h` annotator header · `--sb-h` status bar · `--sidebar-w` 234 · `--left-w`/`--right-w` 256 · `--rnav-w` 64 · `--dt-toolbar-h` drawing toolbar |
| Radius | `--r-xs` 6 · `--r-sm` 9 · `--r-md` 13 · `--r-lg` 18 · `--r-xl` 22 · `--r-full` |
| Shadow | `--sh-sm`, `--sh-md`, `--sh-lg`, `--sh-accent` (per theme) |
| Motion | `--dur-fast` 120ms · `--dur-base` 180ms · `--dur-slow` 280ms · `--ease`, `--ease-out`, `--ease-in` (all collapse under `prefers-reduced-motion`) |
| Layers | `--z-base` · `--z-sticky` · `--z-nav` · `--z-dropdown` · `--z-overlay` · `--z-modal` · `--z-toast` |

**Breakpoints:** use only these: `max-width: 639px` (mobile), `max-width: 1023px`
(tablet), `min-width: 1024px` (laptop), `min-width: 1440px` (desktop),
`min-width: 1920px` (ultra-wide). Values that vary by viewport belong in the
responsive blocks at the end of `tokens.css`, so components stay breakpoint-free.

**Compact density** (Settings → Layout) rescales `--nav-h`, `--tb-h`, `--sb-h` and
the larger `--sp-*` steps; `modes.css` holds the per-component compact rules.

---

## 5. Components

All in `static/css/components.css`, all driven by tokens. Component knobs in
`tokens.css`: `--btn-radius/-pad-y/-pad-x/-min-h/-min-h-sm/-touch-min-h`,
`--input-bg/-border/-radius/-pad-y/-pad-x/-focus-ring`,
`--modal-radius/-w/-w-wide/-pad-x/-head-pad-y/-body-pad-y/-foot-pad-y/-gap/-close-size`,
`--text-modal-title`, `--fw-modal-title`, `--menu-bg/-border/-radius/-shadow/-item-radius`,
`--switch-w/-h/-knob/-track/-border/-knob-off/-on/-knob-on`, `--icon-btn-size/-size-sm/-radius`,
`--chip-h/-radius/-pad-x`, `--text-chip`, `--fw-chip`, `--btn-pad-y-sm/-pad-x-sm`,
`--badge-radius`, `--table-row-h`, `--tab-h`, `--tooltip-bg/-tx`, and the card set
`--card-bg/-tx/-border/-radius/-shadow/-padding/-opacity/-hover-*` (which Settings →
Card Appearance overrides at runtime).

### 5.1 Button roles: one shape per role, on every page

Pages have their own button classes (45 families were found). Rather than
renaming them in markup, **`scripts/apply_button_roles.py`** holds a `ROLES` table that
maps each family to a role and rewrites that family's shape declarations (radius,
font size/weight, height, padding) in every sheet to the role's tokens:

| Role | Tokens | Families (examples) |
|---|---|---|
| `action` (36px) | `--btn-radius`, `--text-button`, `--fw-button`, `--btn-min-h`, `--btn-pad-y/-x` | `.btn`, `.primary-btn`, `.ghost-btn`, `.vs-start-btn`, `.ubd-browse-btn`, `.proj-create-btn` |
| `action-sm` (30px) | same with `-sm` / `--text-button-sm` | `.ah-complete-btn` (Done), `.tb-btn` (header Export…), `.vs-new-btn`, `.proj-card-open-btn`, `.ds-sel-toggle`, `.mini-btn`, `.ct-btn` |
| `icon` (32px) | `--icon-btn-size`, `--icon-btn-radius` | `.btn-icon`, `.dash-icon-btn`, `.up-icon-btn`, `.rn-toggle-btn` |
| `icon-sm` (24px) | `--icon-btn-size-sm`, `--icon-btn-radius` | `.sb-collapse-btn`, `.section-collapse-btn`, `.cc-del`, `.cc-eye`, `.proj-card-del-btn`, `.kmenu-btn` |
| `chip` (24px pill) | `--chip-h`, `--chip-radius`, `--chip-pad-x`, `--text-chip`, `--fw-chip` | `.ds-pill`, `.ftab`, `.pill-btn`, `.view-list`, `.view-grid` |

Colours are not part of a role (primary/secondary/danger variants keep their own
token colours). **Specialized controls intentionally keep their own geometry**
(still token-driven for colour, font, radius steps, spacing and motion): the
drawing toolbar (`.dt-btn`, `.dt-btn-ai`), project nav rail (`.rn-item`), round
image-nav and zoom pills (`.ah-nav-btn`, `.zc-btn`), panel tabs (`.rp-tab`), Settings
vertical nav, the approved Assign Class picker (`cp-*`), auth brand controls (`l-*`).
**New button class?** Add it to `ROLES` and run the script; change a role's look
in `tokens.css`.

### 5.2 Popups, menus, tooltips, switches, native controls

* **Modals:** two markups exist, the shared `.modal-header/-body/-footer` and the
  annotator's 10 `.modal-head/-body/-foot` dialogs. **Both read the same `--modal-*`
  tokens** (radius, paddings, gap, title size/weight, close size, `--z-modal`,
  `--overlay`). Verified equal in the browser (§8, `ds-controls`).
* **Menus/dropdowns:** account menus (navbar and annotator), kebab menu, dashboard
  sort menu all use `--menu-bg/-radius/-shadow`.
* **Tooltips:** write a normal `title="…"`. `UI` (core/ui.js) shows a themed
  `.ui-tooltip` on hover/keyboard focus (not on touch), parks the native title so it
  doesn't double up, and restores it on leave. This applies to all 115 titled controls.
* **Switches:** `.autosave-toggle .aToggle` reads `--switch-*`. (The Settings
  `.switch` CSS was dead and has been removed.)
* **Native checkbox/radio/range/progress:** `accent-color: var(--accent)` in
  `base.css` for every page. Per-split colour-coded sliders keep their own colours.

### 5.3 "Add to Dataset" card (Upload page + Annotate page)

There used to be **three** separate implementations of this card: the Upload
dialog (`usp-*`, 480px wide), the Annotate floating panel (`atd-*`, 340px), and an
unused third modal (`sdm-*`), each with its own CSS and different sizes, fonts
and buttons. Now there is **one component**, `.ui-split-card` in `components.css`,
with identical markup in both places in `templates/pages/annotate.html`:

| Entry point | Container | Opens from |
|---|---|---|
| Upload page | `#uspModal.ui-split-overlay` (centred dialog over a scrim) | batch card ⋮ → *Add to dataset* |
| Annotate page | `#atdPanel.atd-panel.ui-split-card` (anchored above the pill) | bottom-right *Add to Dataset* pill |

Change it in one place:

```css
/* tokens.css */
--split-card-w:    360px;          /* both cards' width            */
--split-card-pad:  var(--sp-4);    /* header/body/footer padding   */
--split-card-gap:  var(--sp-3);    /* space between body sections  */
--split-stat-size: var(--fs-18);   /* the three numbers            */
--split-bar-h:     22px;           /* Train/Val/Test bar height    */
--split-train / --split-val / --split-test (+ -tx): split colours
```

Title/close size come from the modal tokens (`--text-modal-title`, `--modal-close-size`);
the buttons are the shared `.btn` (action role). Behaviour is shared too:
`rebalanceSplit()` in `main.js` keeps Train+Val+Test = 100 in both cards (the
Annotate card previously let the total go wrong and disabled Create). The JS
drives the card only by element IDs (`usp*`/`batch*`, `atd*`), so restyling never
needs a JS change. The browser phase `ds-split-card` measures both cards
(width, height, section heights, type sizes, radius, button sizes) and fails if
they differ in any theme/viewport.

### 5.4 Classes page (`#classes`)

Full-width, two-column layout (`static/css/classes.css`, layout only):

* **Main column**: header (title + count, summary, `.ui-search`, Sync/Export
  `.btn`s), the add-class bar (swatch + `.form-input` + `.btn-primary`), and the
  class list as a shared **`.ui-table`**. Clicking a class name opens the **Rename
  class** popup (`#clsRenameModal`, the annotator modal structure, so `--modal-*`
  tokens apply): current name, colour and `ID n` badge, annotation + image counts,
  new-name field with an `old → new` preview. Rename is disabled until the name
  changes; Enter saves; Esc / Cancel / × / backdrop close without saving;
  duplicate names and server/network errors show inside the popup and it stays
  open. The server's answer is checked, so a refused rename is never shown as saved.
  **Renaming never changes the class ID**; labels store only the ID.
* **Row actions** live in a ⋮ menu (shared `KebabMenu`): Rename…, Change colour…,
  Change ID…, Delete class. **Sortable** headers (Name, ID, Annotations, Images,
  `aria-sort`), **filter chips** All / In use / Unused (chip role tokens), share % per
  class, `/` focuses search. Counts show a skeleton while `/stats` loads and "—" +
  Retry if it fails (never fake zeros). New classes default to the palette colour
  most distinct from existing classes (`_clsSetNextColour`). Insights are
  interactive: a balance row jumps to and flashes its class; "Show unused" filters.
* **Change ID** (⋮ → Change ID… → `#clsReindexModal`): pick a new ID; if taken, Swap
  or Move-and-shift (mappings built in `main.js _clsReindexMapping`). A dry run of
  `POST /classes/reindex` previews the classes and label lines that change; Apply
  rewrites them server-side (`app/core/class_reindex.py`: backup zip, atomic writes,
  rollback) and remaps this tab's loaded boxes (`_clsRemapInMemory`).
* **Insights panel** (`--cls-side-w`, 320px): Overview KPIs (classes, annotations,
  labelled images / total, unused classes), Class balance (share of all annotations
  per class), Needs attention (`.ui-alert`s: unused classes, ≥10× imbalance, images
  with no labels). Rendered by `main.js _renderClassInsights()` from `/stats`.
* Width tokens: `--cls-page-max: var(--content-wide)`; below 1024px the panel moves
  under the table as a card grid; below 640px table rows become cards that keep ID,
  annotation and image counts.
* Data: `/stats` returns `class_counts[].id` (it was missing, so every class showed 0)
  and `labelled_images` (images with ≥1 box). `annotated_images` means images marked
  **Done**, which is a different number; don't label one as the other.

### 5.5 Versions page (`#versions`)

`static/css/versions.css` (layout only). List (`--ver-list-w`, 340px) + detail card
(`--ver-detail-max`); split colours are the shared `--split-train/-val/-test` tokens,
the same as the Add-to-Dataset card. List items are keyboard-selectable (`role=option`,
↑/↓, Enter) with a ⋮ `KebabMenu` (Download ZIP, Copy folder path, Delete version →
`UI.confirm`). The detail shows KPIs (Images, Classes, Train/Valid/Test with %), the
split bar, export format, project-relative folder path + Copy, and any recorded
preprocessing/augmentation with an honest "README only" note. Version numbers come
from the name (`_verNum`), so deleting one never renumbers the rest. ≤1023px: list
OR detail (`.ver-page.has-selection`) with a back button. The compact project header
for Dataset/Classes/Versions is ONE rule in `annotate-v2.css`. Readable text uses
`--tx2`; `--tx3` is for placeholders/disabled only (≈1.7:1 on the dark background).

| Component | Markup | Notes |
|---|---|---|
| Button | `<button class="btn btn-primary">Save</button>` | variants `btn-primary`, `btn-secondary`, `btn-ghost`, `btn-danger`, `btn-danger-solid`; sizes `btn-sm`, `btn-lg`, `btn-full`; `btn-icon`; 44px touch target on coarse pointers |
| Input / select / textarea | `<label class="form-label" for="e">Email</label><input class="form-input" id="e">` | `.form-group`, `.form-error`, `.form-success`; focus ring from `--input-focus-ring` |
| Search field | `<label class="ui-search"><i class="fas fa-search" aria-hidden="true"></i><input class="form-input" type="search" placeholder="Search…"></label>` | |
| Card | `<div class="card">…</div>` | look comes from the `--card-*` tokens |
| Badge | `<span class="badge badge-owner">Owner</span>` | `badge-owner/-editor/-viewer/-danger` |
| Modal | `.modal-overlay > .modal > .modal-header / .modal-body / .modal-footer` | docks to the bottom on phones |
| Confirm dialog | `if (await UI.confirm({title, message, confirmText, danger:true})) …` | themed, Escape/backdrop = cancel, focus trapped; replaces `confirm()` |
| Toast | `UI.toast('Saved')`, `UI.toast('Failed', 'error')` | types `success/error/warning/info`; inserts text only; max 4 visible |
| Tabs | `<div class="ui-tabs" role="tablist"><button class="ui-tab" role="tab" aria-selected="true">A</button>…</div>` + `UI.tabs(el, onChange)` | arrow/Home/End keys |
| Table | `<div class="ui-table-wrap"><table class="ui-table">…</table></div>` | wrapper scrolls sideways |
| Tooltip | `<button title="Delete image">` | automatic themed `.ui-tooltip` via `core/ui.js` |
| Menu surface | any dropdown: `background/border-radius/box-shadow: var(--menu-*)` | |
| Add-to-Dataset card | `.ui-split-card` › `.ui-split-head` / `.ui-split-body` (`.ui-split-stats`, `.ui-split-bar`, `.ui-split-rows`, `.ui-split-note`) / `.ui-split-foot` (`.btn btn-secondary` + `.btn btn-primary`) | ONE card for both entry points; see §5.3 |
| Switch | `<label class="autosave-toggle"><input type="checkbox"><span class="aToggle"></span></label>` | `--switch-*` |
| Alert | `<div class="ui-alert ui-alert-warning" role="status"><i class="fas fa-triangle-exclamation"></i><span>…</span></div>` | `-info/-success/-warning/-danger` |
| Spinner | `<span class="ui-spinner" role="status" aria-label="Loading"></span>` | `ui-spinner-lg` |
| Empty / error state | `<div class="empty-state">…</div>`, add `ui-error-state` for failures | `.empty-icon`, `.loading-state` |
| Page header | `<header class="ui-page-header"><div><nav class="ui-breadcrumb">…</nav><h1 class="ui-page-title">…</h1><p class="ui-page-subtitle">…</p></div><div class="ui-page-actions">…</div></header>` | used by Members |
| Kebab menu | `.kmenu-btn` + `KebabMenu` in `static/js/core/utils.js` | re-parented to `<body>` |

**Naming:** older primitives keep their names (`.btn`, `.form-*`, `.card`,
`.badge`, `.modal`, `.empty-state`, `.kmenu`). Components added by this pass use a
`ui-` prefix, because `.spinner`, `.toast`, `.card-title`, `.tabs` were already
styled by page sheets and a global rule under those names would leak into them.

**How to change a component globally:**

```css
/* tokens.css: every button on every page becomes pill-shaped and roomier */
--btn-radius: var(--r-full);
--btn-pad-x:  var(--sp-6);

/* tokens.css: every card gets a smaller radius and no hover lift */
--card-radius: var(--r-md);
--card-hover-transform: none;
```

**How to add a reusable component:**
1. Add any new knobs to the theme-independent `:root` block in `tokens.css`
   (and per-theme values to both theme blocks if they're colours).
2. Add the rules to `components.css` under a `ui-` class, using tokens only.
3. If it needs behaviour, add a function to `static/js/core/ui.js` and expose it on `UI`.
4. Add a row to the table above with its markup.
5. Run `python scripts/check_design_tokens.py` and the browser checks in §8.

---

### 5.6 Wizard dialog (`.ui-wizard`, 14 Nov 2026)

Multi-step flows use ONE shared component in `components.css` (first user: the
Create Dataset Version wizard). A centred card, never a side drawer:
header · **step rail on the left** (label + hint per step, ✓ for done steps,
done steps clickable) · scrolling content · footer pinned at the bottom. Tablet
(≤1023px): the rail becomes a step strip under the header. Phone (≤639px): full
screen, and only the current step keeps its label. Geometry tokens:
`--wizard-w` 960px, `--wizard-h` 680px, `--wizard-rail-w` 232px,
`--wizard-step-dot` 28px, `--wizard-line-w` 2px; spacing/radius/title come from the
`--modal-*` tokens. Esc closes (an open popup inside closes first); focus goes to
the first field on open and back to the opening button on close. Page CSS
(`.vw-*` in `main.css`) styles step *content* only. Verified by
`browser_audit.py wizard` (centred, inside viewport, rail beside content,
navigation/Esc/close, 4 themes × 3 sizes, screenshots in `.audit-browser/wizard/`).

## 6. Layouts

* **Content pages** (Dashboard, Members, Settings, Help) use the shell in
  `layout.css`: the top navbar from `templates/layout/navbar.html` (which also
  carries the `AccountSettings` script; pages that draw their own chrome set
  `{% set hide_navbar = true %}` *before* including it), then a page container.
  Dashboard replaces the navbar with its own rail and top bar.
* **Project workspace** (`/pages/annotate`, six hash sections) keeps its fixed
  shell: header (`--tb-h`), shared right navigation rail (`.right-nav`, follows the
  selected theme in all six sections), left/right panels (`--left-w`/`--right-w`),
  floating drawing toolbar (`--dt-toolbar-h`) and status bar (`--sb-h`, Annotate only).
  It shares all tokens and components; only its geometry is specific.
* Mobile: navbar sidebar becomes an off-canvas drawer below 1023px; modals dock to
  the bottom below 639px; toasts span the width.

---

## 7. Theme management

* Light and dark are both derived themes in `tokens.css` (`:root` = dark,
  `:root.light-mode` / `[data-theme="light"]` = light). Custom colours and
  compact density are modes applied on top.
* `static/js/theme.js` runs synchronously in `<head>` (via the partial) and applies
  the saved choice before first paint. Storage keys: `am_theme_mode`
  (`dark`/`light`/`custom`), `am_accent_color`, `am_layout_mode`, `am_custom_bg/_text`,
  `am_card_*`. **The global key wins over the per-user `…_<uid>` copy, everywhere.**
  Settings now reads them in the same order as `theme.js`; before this, it read the
  per-user key first and could flip the app back to a stale theme.
* Custom mode: `applyCustomTheme()` derives surfaces, `--tx2`, `--tx3` and
  `--accent-text` from the two picked colours (§2.4); `applyAccent()` resyncs
  `--accent-text`. Any new derived *text* token must be recomputed there too.
* **Dark styles (14 Nov 2026).** Dark Mode has four looks, chosen in Settings →
  Theme → *Dark style*: **Classic** (graphite + teal, default), **Midnight Blue**
  (deep indigo, electric blue `#3a66f7`, blue glow), **Navy** (blue navy +
  emerald `#1ec97e`), **Carbon** (neutral black + vivid blue `#146ef5`). Each is
  ONE block in `tokens.css` ("DARK STYLES", `:root[data-dark-style="…"]
  :not(.light-mode):not(.custom-mode)`) that re-declares surfaces, borders,
  text tiers, accent, `--on-fill`, `--ambient` (the page glow) — everything
  else derives. `theme.js` sets `data-dark-style` from `am_dark_style` before
  first paint (`ThemeEngine.setDarkStyle/clearAccent/darkStyles`). Picking a
  style drops an earlier accent pick so the style's accent shows; a later
  accent still wins and `--accent-text` is recomputed against the style's real
  surfaces (`liveSurfaces()`). Light and Custom ignore the style. Adding a style
  = one token block + one swatch in `settings.css` + one option in
  `settings.html`. Contrast per style is measured (tx2 ≥ 6:1, tx3 ≥ 4.5:1,
  accent text ≥ 5.5:1, on-fill ≥ 4.5:1).
* `--accent-a04…a40` are now `color-mix(in srgb, var(--accent) N%, transparent)`
  in both themes, so accent washes follow any accent (they used to stay teal
  after a user picked another accent).
* Text on a purple fill uses `--on-purple`, never `--on-fill` (white on-fill
  styles made it 3.1:1).
* Switch from code: `ThemeEngine.setThemeMode('light')`. The login page chip and
  Settings both use it and write the same keys.

---

## 8. Verification tooling

| Check | Command | What it proves |
|---|---|---|
| Token guard | `python scripts/check_design_tokens.py` (also in `python -m unittest discover -s tests`) | no hardcoded font family/size/colour or colour fallback outside fenced exceptions |
| Contract tests | `tests/test_design_system.py` | every page uses the head partial; cascade order; all used size steps exist; the guard detects each rule |
| Snapshots | `DS_LABEL=before python scripts/browser_audit.py ds-snapshots` then (after the change) `DS_LABEL=after …` and `python scripts/compare_design_snapshots.py before after` | pixel diff of 14 pages × light/dark × desktop/tablet/mobile (84 shots; repeat runs are identical, so any diff is real) |
| Propagation | `python scripts/browser_audit.py ds-propagation` | overrides `--font-sans`, `--font-scale` and `--accent` *only* in the token layer and asserts every page's text and accent follow |
| Geometry knobs | `python scripts/browser_audit.py ds-geometry` | sets `--radius-scale` 2, `--space-scale` 1.5, `--shadow-strength` 0, `--motion-scale` 2 and measures, per visible element on every page/theme, whether its radius/padding/shadow/transition followed; non-followers are listed by name |
| Inventory | `python scripts/browser_audit.py ds-inventory` | every visible interactive element per page/theme: font from token? size on scale? shared class? number of distinct button shapes |
| Controls | `python scripts/browser_audit.py ds-controls` | themed tooltip shown + title restored; switch differs off/on; annotator modal and shared confirm have equal geometry; kebab and account menus share one surface; native checkbox accent, in light/dark × desktop/mobile |
| Add-to-Dataset card | `python scripts/browser_audit.py ds-split-card` | Upload dialog and Annotate panel are pixel-equal in size/type/radius/buttons, fit the viewport and rebalance identically, light/dark × desktop/tablet/mobile; screenshots `.audit-browser/split-card-*.png` |
| Contrast | `python scripts/browser_audit.py ds-contrast` | every visible text element on 14 pages + the 5 Version-wizard steps, in light, dark, custom-dark and custom-light: computed colour vs composited background ≥ 4.5:1 (3:1 large). Undecidable cases (gradient text, image backgrounds) are counted as skipped, not passed |
| Wizard | `python scripts/browser_audit.py wizard` | Create Dataset Version dialog centred and inside the viewport at desktop/tablet/phone in light/dark/custom-dark/custom-light; step rail beside content on desktop; Continue/Back/step-click/Esc/close work; screenshots of every step |
| Dark styles | `python scripts/browser_audit.py dark-styles` | picker only in Dark Mode; each style sets `--bg`/`--accent` on all 14 pages before first paint, drops an old accent; a later accent wins and stays ≥ 4.5:1; Light/Custom ignore it; Reset → Classic. `ds-contrast` and `wizard` also run the three styles |
| Tools (all idempotent) | `scripts/tokenize_typography.py`, `tokenize_geometry.py`, `apply_button_roles.py`, `find_unused_css.py`, `remove_unused_css.py` | re-running reports 0 changes; use `--dry-run` to list stragglers |

Snapshots and diffs land in `.audit-browser/ds/` (git-ignored). Snapshots and
propagation run on the empty disposable fixture, so they show chrome and empty
states, not a loaded image. Annotate's loaded-image states are covered by the
`project` phase.

---

## 9. Checklist for a new page or component

1. `{% set page_css = ['css/<page>.css'] %}` then `{% include 'layout/head_assets.html' %}`
   in `<head>`. Do not link fonts, tokens, base, components or modes yourself.
2. Build from existing components (§5) before writing CSS. Page CSS holds layout only.
3. Use role tokens for text, `--sp-*` for spacing, `--r-*` for radius, semantic colour tokens.
4. Use the breakpoints in §4 only.
5. Toasts and confirmations go through `UI.toast` / `UI.confirm`, never `alert()`/`confirm()`.
6. Check both themes at 1440×900, 768×1024 and 390×844. Run the guard, the unit tests
   and `ds-snapshots` + `ds-propagation` (add the route to `DS_PAGES` in `scripts/browser_audit.py`).
7. If you add a token or component, update this file.

---

## 10. Verified status (14 November 2026)

Measured with the tools in §8 on the disposable fixture (real Chrome, light + dark,
1440×900 / 768×1024 / 390×844). Full regression on the final code: **15 browser
phases, 364 checks, 0 failures**; unit tests 47 run, 46 pass, 1 Windows-symlink skip;
token guard 0 violations; every converter idempotent.

| Requirement | Status | Evidence | Remaining |
|---|---|---|---|
| Every page uses the design system | **Done** for all 8 rendered templates (14 page states) | `test_every_page_uses_shared_head`; `ds-propagation` 28/28 | `templates/pages/upload.html` is unrendered legacy, not migrated |
| Fonts, sizes, colours central | **Done** | guard 0; `ds-inventory`: 100% of visible elements use the token font + an on-scale size | deliberate exceptions fenced with `ds-allow` (auth brand palette, swatches, photo marks) |
| Radius, spacing, shadows, motion central | **Done (measured)** | `ds-geometry`: radius 496/496, padding 672/678, shadow 23/23, motion 566/566 | 6 padding values: dashboard top bar/body and the search icon gap (`1em`) |
| Changing a token updates components | **Done (measured)** | `ds-propagation` + `ds-geometry` override only tokens and measure each element | canvas annotation labels keep their pixel size by design |
| Buttons consistent | **Partial** | role registry (§5.1) unifies 30 families into 5 roles | distinct button shapes per page are still 21 on Annotate, 8–11 on other project sections, mostly specialised tools/nav/chips; most annotator buttons don't use `.btn` markup |
| Modals, menus, tooltips, switches, checkboxes | **Done for the listed components** | `ds-controls` 20/20 (both themes × desktop/mobile) | annotator dialogs still use native `confirm()` in `main.js` |
| Tables, cards, tabs, badges | **Partial** | Classes uses `.ui-table`; Add-to-Dataset card unified (`ds-split-card` 6/6) | other lists/cards (Dataset, Versions, Upload) still page-specific markup on tokens; `.ui-tabs` not adopted yet |
| No duplicate / dead CSS | **Partial** | 846 dead selectors + 9 exact duplicates removed; CSS 14,512 → 13,493 lines | 33 unreferenced class names (mostly library components not yet used); 262 selectors still overridden by `annotate-v2.css` over `main.css` (structural) |
| Responsive | **Done for tested states** | every phase runs at 3 sizes; mobile canvas collapse fixed (`probe` 45/45) | physical touch devices, Safari/Firefox, custom/compact modes not snapshot-tested |
