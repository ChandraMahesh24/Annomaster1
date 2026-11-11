# Handoff: AnnoMaster Workspace Dashboard Redesign

## Overview
Modernized redesign of the AnnoMaster workspace dashboard (workspace header, KPI summary, and project grid) shown to a workspace owner after login.

## About the Design Files
The bundled file (`Dashboard.dc.html`) is a **design reference built in HTML** — a prototype showing intended look, layout, and behavior. It is not production code to copy into the app. The task is to **recreate this design in the existing React codebase**, using its existing component library, styling approach (CSS-in-JS, Tailwind, CSS modules, etc.), and data layer — replacing the old dashboard UI with this new one.

## Fidelity
**High-fidelity.** Colors, spacing, typography, and layout are final; recreate pixel-close using the codebase's existing patterns/components rather than inline styles.

## Screens / Views

### Workspace Dashboard
**Purpose:** Owner views workspace info, KPI totals, and the list of projects in the workspace; can create/share, sort/switch view, and jump into a project.

**Layout:** Two-column shell — fixed 252px left sidebar + flexible main content area, `min-height: 100vh`, `display:flex`, font-family Helvetica/Arial.

**Sidebar (252px, white bg, 1px right border `oklch(0.93 0.005 240)`, 24px/16px padding):**
- Logo row: 30×30 rounded-9px gradient tile (`oklch(0.62 0.14 165)` → `oklch(0.5 0.13 175)`) + wordmark "AnnoMaster" (brand color on "Master": `oklch(0.55 0.14 165)`), 17px bold.
- Nav list: "Workspaces" (active, pill bg `oklch(0.95 0.03 165)`, text `oklch(0.4 0.1 165)`), "Projects", "Settings" — 13.5px, 9px/10px padding, 8px radius.
- "Your Workspace" section: uppercase 10.5px label + add (+) button (22×22, 1px border, 6px radius); workspace row "mahes" — icon tile + 13.5px bold on `oklch(0.97 0.005 240)` bg, 9px radius.
- Footer (pinned via `margin-top:auto`): 28px circular avatar (gradient, initial "M") + email, 12.5px, truncated with ellipsis, top border separator.

**Top bar (white, bottom border, 18px/40px padding, flex row):**
- Breadcrumb: "Workspaces / mahes" (13.5px, active segment bold).
- Search input placeholder (max-width 360px, `oklch(0.96 0.005 240)` bg, 9px radius, 13.5px).
- Notification bell icon (with red unread dot) + 32px circular avatar.

**Header block (36px/40px page padding):**
- Title row: "mahes" (26px bold) + "OWNER" pill (`oklch(0.94 0.04 165)` bg / `oklch(0.5 0.12 165)` text, 999px radius, 10.5px bold).
- Subtitle: "WS-470501 · N projects" (13.5px, `oklch(0.55 0.01 250)`).
- Actions: "Share" (outline button) + "+ New Project" (filled, `oklch(0.55 0.14 165)` bg, white text, subtle shadow). Both buttons: `white-space:nowrap`, `flex-shrink:0` to prevent text wrap.

**KPI row (3-col grid, max-width 760px, 16px gap):** Cards for Total images / Completed (+ % delta) / Pending. Each: white bg, 1px border `oklch(0.93 0.005 240)`, 14px radius, 18px/20px padding, small icon chip top-right, 26px bold value.

**Projects section:**
- Section header: uppercase "Projects" label + right-aligned "Sort: Recent" control + grid/list view toggle (segmented control, grid icon active by default).
- Grid: `repeat(auto-fill, minmax(280px,1fr))`, 20px gap.
- **Project card:** white, 1px border, 16px radius, hover lifts (`translateY(-3px)`) with deeper shadow. Structure top→bottom: 130px gradient thumbnail placeholder with folder icon glyph; 4px progress bar (gradient fill, width = completion %); body (16px/18px padding) with name (15.5px bold) + % right-aligned, 3 stat pills (images/done/pending — blue/green/amber tint families), footer row with "Updated {relative time}" + overlapping collaborator avatar stack (20px circles, -6px overlap, white border).
- **Ghost "New Project" card:** dashed border (`oklch(0.85 0.005 240)`), centered "+" circle icon + label, hover turns brand-teal.

## Interactions & Behavior
- Card and buttons: hover state changes (background shift on buttons, shadow/lift on project cards, border/text color on ghost card, sidebar nav row hover bg).
- View toggle and sort control are visual-only in the prototype — implement as real state (grid vs. list layout, sort key) in the app.
- Search input is a static placeholder — wire to real project filtering.

## State Management
- `projects`: array of `{ name, images, done, pending, updated, avatars[] }` — computed fields needed: `pct = round(done/images*100)`, and pill/percentage label strings.
- KPI totals (`Total images`, `Completed`, `Pending`) are aggregates over `projects` — compute from the same array rather than hardcoding.
- Sort key (e.g., "Recent") and view mode ("grid" | "list") as local UI state.

## Design Tokens
- **Colors:** background `oklch(0.985 0.004 240)`; text `oklch(0.2 0.01 250)`; borders `oklch(0.93 0.005 240)`; brand/teal accent `oklch(0.55 0.14 165)` (gradient partner `oklch(0.5 0.13 175)`); stat pill families — blue `oklch(0.45 0.13 250)` on `oklch(0.95 0.03 250)`, teal-green `oklch(0.45 0.13 165)` on `oklch(0.95 0.04 165)`, amber `oklch(0.5 0.13 75)` on `oklch(0.96 0.05 75)`.
- **Typography:** Helvetica/Arial; sizes used: 26px (h1), 17–15.5px (card/section titles), 13.5px (body/nav), 12–10.5px (labels/pills/meta).
- **Radius:** 16px (cards), 14px (KPI cards), 9px (buttons/inputs), 8–7px (chips/pills), 999px (badges), 50% (avatars).
- **Shadow:** resting card `0 1px 3px oklch(0.2 0 0 / 0.04)`; hover `0 10px 28px oklch(0.2 0 0 / 0.1)`; primary button `0 2px 8px oklch(0.55 0.14 165 / 0.3)`.

## Assets
No external images — thumbnail folder icon and all icons are drawn with plain CSS shapes (divs/borders), not SVG/icon fonts. Replace with the app's real icon set and real project thumbnails where available.

## Files
- `Dashboard.dc.html` — full design reference (inline-styled HTML) for the dashboard described above.
