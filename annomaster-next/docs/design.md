# AnnoMaster-next — Design System

The port keeps the original's visual language but fixes what it never finished:
real dark/light theming, responsive layout, and clean typography. **Improve, don't
clone** (see [rules.md](rules.md) §A).

## 1. Token layer (single source of truth)
Cascade contract:
```
tokens.css → base.css → layout.css → <page>.css → modes.css   (ported)
        → react-glue.css → app.css                            (React additions)
```
- **`tokens.css`** — every colour, type, space, radius, motion, z-index token.
  Dark = `:root`; light = `:root.light-mode`. Both are *derived* — neither is baked
  into a component sheet. Adding a theme = adding one block here.
- **Compatibility alias layers**: `upload.css` (`--up-*`) and `annotate-v2.css`
  (`--v2-*`) keep private token namespaces that now **alias** the semantic tokens,
  so those sheets are theme-aware without rewriting ~1,500 rules. Change the alias
  block at the top, not the rules below it.

## 2. Colour rules
- **Never hardcode a colour** in a component sheet — use a token.
- **Never** `var(--x, #hex)` colour fallbacks (pins the property to one theme).
- Text on a saturated fill uses the **on-fill** token, not `#fff`/`#000`:
  - `--on-fill` (generic), `--up-on-primary` (accent fill),
    `--up-on-secondary-container` (light purple tint — white would be invisible).
  These invert brightness between themes; hardcoding white breaks light mode.
- Alpha ramps: `--ink-a02…a30` (hairline borders/hover), `--accent-a04…a40`
  (accent washes).

## 3. Typography
- **UI font: Inter** (`--font-sans: 'Inter', -apple-system, 'Segoe UI', …`) — the
  clean, neutral sans-serif Roboflow/most modern web apps use. Loaded in
  `index.html`; falls back to Segoe UI if the web font is blocked.
- **Mono: JetBrains Mono** (`--font-mono`) for counts/ids/coordinates.
- Do **not** reintroduce `'Sora'` literals — all were routed through `--font-sans`.

## 4. Layout & responsiveness
- **Breakpoints**: 639 (mobile), 1023 (tablet), 1024+ (laptop), 1440+ (desktop),
  1920+ (ultra-wide). Viewport-varying values belong in `tokens.css`.
- **Upload page** = 3-column grid (Active Work / Upload / Completed Datasets),
  widened side panes so cards have room; collapses to 2-col then 1-col.
- **Annotate page** = left Media Library · canvas · right panel (flex row); side
  panels hide < 639px.
- **Cards must reflow, never clip text.** Batch/dataset cards use a wrapping row
  with a capped width; action buttons use `min-width: max-content` so labels wrap
  rather than truncate.

## 5. Component patterns
- **Batch card** (`.uhp-*`, styled under `#page-upload`): compact header (icon ·
  date · source · delete), thin progress bar + single stat line, one assignee line,
  one action row (Annotate · Assign · Dataset, equal width).
- **Dataset card** (`.upds-*`): icon · total chip · train/valid/test split bar.
- **Modals**: `.usp-*` (add-to-dataset split sliders), `.bam-*` (assign member
  picker), `.modal-*` (video frame extraction).
- **Smart Detect bar** (`.sd-bar`): model select + upload `.pt`, confidence/overlap
  sliders, Approve N, mode (Review/Auto), re-run. Floats beside the draw-toolbar.
- **Canvas overlays**: `.draw-toolbar` (top-center), `.zoom-controls` (bottom-left
  pill), `.img-nav-bar` (bottom-center ‹ n/total ›), `.cls-popup` (on the box).

## 6. Canvas is painted by JS
CSS tokens can't reach a `<canvas>`. `Canvas.tsx` reads live token values off
`<html>` (`token()` helper) for grid/box/handle colours, so the canvas follows the
theme. Class colours come from the project's class palette (not themed — theming
them would make a saved box appear to change class on theme switch).

## 7. Deliberately NOT themed (do not "fix")
- Class palette (identifies annotation classes).
- The `.rn-*` left nav rail (`--v2-brand-dark`) — fixed dark brand surface in both
  themes; foreground `--v2-on-brand`.
- Canvas resize **handles** (white fill + class-colour ring) — they sit on the
  user's image, not a themed surface.

## 8. Floating-surface positioning
`--dt-toolbar-h` (tokens.css) is the single source for the drawing toolbar height;
other floating panels position relative to it. Translucent surfaces use
`--v2-frost` (derived from `--surface`) — **never** `--v2-on-brand` (a foreground
token; using it as a background pins the surface white in both themes).
