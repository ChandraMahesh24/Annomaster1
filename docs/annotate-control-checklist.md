# Annotate control audit — permanent continuation checklist

**User approval:** the compact Assign Class picker was accepted on13 November2026.
Preserve its sizing, object-aware placement, draggable header and theme/keyboard
behavior. See the latest approved checkpoint in PROJECT_AUDIT_AND_PROGRESS.md.

Updated 13 November 2026. Read PROJECT_AUDIT_AND_PROGRESS.md first. PASS is bounded
to the action described; it is not complete acceptance of every control state.
Use disposable fixtures, never the user's real annotations. Do not rely on source
existence, a theme background, or a successful panel-open test alone.

## Required matrix for every new or changed control

Test light and dark themes; desktop1440x900, tablet768x1024, mobile390x844;
empty and loaded images; hover/focus/disabled states; keyboard; popup content and
close/Escape; navigation away while open and return; loading, success and failure;
save/reload/API consistency; permissions and concurrent-edit behavior where relevant.
Mark unperformed cells PENDING or BLOCKED, never PASS. Record expected/actual and
the exact named browser assertion. Popups must be inspected while open.

## Verified actions and remaining cases

Evidence: scripts/browser_audit.py `project`, `ai`, and `media` phases;
docs/audit-browser-results.json. Latest project sweep adds both-theme property,
raw/notes, modal navigation, split, save errors and completion tests. Earlier AI
inference is bounded separate evidence, not newly tested across all themes.

| Controls / area | Expected and actual tested behavior | Status / unfinished cases |
|---|---|---|
| Box tool, class list, Confirm | Mouse draw/class confirmation/persistence/reload succeeds | PASS selected flow; nested/rotated/edge geometry still PENDING |
| Polygon, class picker, Undo, Redo | Real three-point polygon confirms; undo/redo restores counts | PASS; cancellation no longer pushes polygon history; extensive vertex editing PENDING |
| Select/Edit, Pan | Mode selection works; Properties selects annotation through list | PASS mode entry only; actual drag move/resize and pan gestures PENDING |
| Labels, Grid, Repeat | Toggle state, visible notification background, close, restore state in both themes | PASS; opening animation not contrast certification |
| Zoom+/−, Fit, lock | State changes; mobile zoom/navigation do not overlap | PASS; gesture/touch zoom PENDING |
| Toolbar horizontal scroll | All tested drawing groups reachable at three sizes/both themes | PASS selected IDs; physical touch/assistive tech PENDING |
| Autosave switch | Visible label toggles real autoSave boolean in both themes | PASS; debounce conflict/race stress PENDING |
| Save shortcut | Successful save, injected409→Error, retry→Saved | PASS both themes; real multiuser409 still PENDING |
| Done | Persists before advancing; failed save refuses completion; Null stays Null | PASS final sweep; no full concurrent-navigation guarantee |
| Header/bottom image navigation | Next/previous/Null roundtrip restores annotations | PASS selected flow; crossing long paginated/filtered queues PENDING |
| Right panel Labels/Properties/Raw/Notes | Tabs opened in both themes | PASS; every dynamic row/menu not yet covered |
| Properties X/Y/W/H + Apply | Oversized input clamps to image; undo restores geometry | PASS both themes; all numeric/keyboard edge cases PENDING |
| Property Class | Switching0→1→0 updates selected annotation | PASS both themes; invalid/missing class races PENDING |
| Delete selected + Undo | Selected annotation removed and restored | PASS both themes; bulk deletion PENDING |
| Set as Project Cover | Actual button action produces cover success notification | PASS both themes; cross-project image comparison PENDING |
| Raw Copy | Actual clipboard readback has YOLO five-field record | PASS both themes on loopback; insecure-LAN fallback implemented, real LAN clipboard PENDING |
| Notes Send / Clear | Add markup-like note as literal text; no injected img; clear succeeds | PASS both themes. SESSION ONLY, explicitly labeled not synced; durable notes missing |
| Help, Settings, Stats, Import, Split dialogs | Open, Escape close, reopen, hash navigation closes, return stays closed | PASS both themes; all inputs of each dialog not complete |
| Settings brightness Apply | Slider change and state apply | PASS earlier; contrast/opacity/line/grid/reset combinations PENDING |
| Split inputs / Submit | Dedicated JSON endpoint, zero ratios supported, real successful result | PASS both themes; DB reviewed images only, legacy folder split unsupported with explicit error |
| Split permissions/invalid ratios | Viewer403, invalid400, valid canonical `valid` DB value | PASS API; frontend multiuser layout PENDING |
| Import ZIP chooser | Real YOLO preview/import and annotation appear | PASS media phase; all formats/error/cancel combinations PENDING |
| Export | Actual ZIP inspected for paired image/confirmed labels, excludes sidecars | PASS earlier selected flow; duplicate basename collision audit PENDING |
| Smart Detect / AI Annotate open-close-navigation | Open either, leave to each other section, return closed; hash route closes | PASS; running-inference server cancellation not implemented/claimed |
| Smart Detect model/run/upload | Exact YOLO11n200 and invalid checkpoint422 | PASS earlier AI phase; full both-theme controls/thresholds/model variants PENDING |
| Prompt phrase add/remove, tabs, polarity, run | Real SAM3 text200 plus selected panel controls | PASS earlier AI phase; exemplar gestures, full settings and all theme states PENDING |
| Left/right collapse, navigation rail | Selected collapse/reopen and six-section links exercised | PASS selected flows; resizer drag/min widths/keyboard PENDING |
| Image search/status/split/per-page | Source inventory exists | PENDING exact result assertions on long annotation queues |
| Class picker search/add/cancel/delete | Existing confirmation, search/no-match, inline new class and Cancel in both themes | PASS selected flows; keyboard/delete/duplicate validation still pending |
| Header project selector/new/delete/account menus | Other dashboard CRUD evidence exists | PENDING editor-specific flows in both themes |
| Create Dataset floating panel/sliders/confirm | Upload batch→dataset modal verified earlier | PARTIAL; all inline controls and zero-ratio variants PENDING |
| Lock banner/force unlock | API lock protection verified earlier | PARTIAL; simultaneous owner/editor/viewer browsers PENDING |
| Class row visibility/delete; annotation row menus | Source inventory exists | PENDING destructive/remap/visibility interactions |
| Empty Import/Upload and error image | Empty render verified earlier | PARTIAL; actual empty-state button flows PENDING |

Do not mark the full page or full UI audit complete from this table. Next work:
remaining PENDING rows, starting with remaining class-picker cases and filtered/paginated queue
controls, then inline dataset panel, editor project/account menus and real
multiuser conflicts. Update this checklist alongside permanent project memory.

Compact Assign Class follow-up: six theme/viewport combinations now test220px width, canvas bounds, non-overlap with a newly drawn test box, pointer dragging and cancellation. All passed; exact full-image/long-list/corner/zoom matrix remains incomplete. See permanent memory and retained screenshots.

### Classes route follow-up — 14 November 2026

`#classes` is separate from the annotation canvas class sidebar. Its dedicated
Chrome phase now passes 15/15 groups: add/duplicate, direct rename (Enter/Escape/blur,
reload, empty/duplicate rejection, network failure), literal special characters,
color change event/persistence, search/empty state, delete cancel/confirm, export
content and sync response. Light/dark desktop/tablet/mobile checks include actual
rename and delete-cancel interactions and all metadata/action bounds. Classes →
Annotate → Classes restores the appropriate header. See permanent memory for
limitations; this does not close pending canvas-sidebar or multiuser tests.

### Compact layout sidebar regression — 14 November 2026

Settings Compact → Annotate: reproduced header overlap (workspace38px versus
header52/148/184px). Shared shell tokens fixed. New `compact-sidebar` phase:
12/12 PASS across compact/expanded, light/dark, desktop/tablet/mobile. Verified
Labels/Properties/Raw/Notes tab text bounds, panel switching, collapse/restore,
and tab strip below header. No console/network failures. Does not certify every
control inside those panels. Keep responsive header and workspace offsets aligned.

### Shared header scope — 14 November 2026

`header-scope` 12/12 PASS: light/dark, compact/expanded, three widths. In every
group, five non-editor sections hide image/progress/save/editor actions; Annotate
restores them. Project switcher/account retained; direct Upload reload checked.
This closes the reported header leak only; upload workflow coverage is unchanged.
