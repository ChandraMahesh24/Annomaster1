# AnnoMaster — project audit and progress

## Latest user-approved checkpoint — 13 November 2026

User confirmed the compact **Assign Class** interaction is acceptable ("this is ok"). Preserve this approved behavior in future sessions:

- Responsive picker width up to220px, maximum height300px, scrollable class list capped132px, tighter rows/footer and concise class search.
- Placement considers the full pending annotation, ranks positions by overlap, and clamps the picker inside the canvas. Header can be dragged to reposition it. Full-canvas annotations can still leave no overlap-free position; dragging is the fallback.
- Preserve Confirm/Cancel, class search/addition, keyboard selection, theme colors and annotation save semantics.
- Also retain the related mobile fix separating Add to Dataset from zoom/navigation and preventing collapsed right sidebar pointer interception.
- Implementation: `static/js/main.js` (`_showClassPopup`), `static/css/annotate-v2.css`, `templates/pages/annotate.html`; regression in `scripts/browser_audit.py`.
- Verification:20/20 selected project browser workflow groups passed; picker placement/drag/cancel checked in light/dark at desktop1440x900, tablet768x1024, mobile390x844. Evidence: `docs/audit-browser-results.json`, screenshots in `docs/audit-screenshots/assign-class-light-{desktop,mobile}.png`.

**Design system (13 November 2026, later):** a centralized design system now exists.
Read `DESIGN_SYSTEM.md` before any UI change; details and test results are in the
"Centralized design system" section at the end of this file. Open issue found
during it: the **Annotate mobile canvas collapses to ~26px** (present in the
pre-change baseline; tied to the unfinished Media Library redesign). It is the
top next task.

Future continuation: read this file completely, then `docs/annotate-control-checklist.md`.
Continue pending coverage from that checklist. Do not redesign or undo this approved
picker unnecessarily, repeat completed work without cause, or describe the whole
application audit as complete. Earlier chronological entries below explain prior
defects and changes; this checkpoint records the latest accepted picker behavior.

Last updated: 13 November 2026 (Asia/Calcutta). **The exhaustive audit is NOT complete.**

## Mandatory continuation protocol

Read this entire file before changing code. Inspect Git changes, preserve existing work, identify unfinished checks, and update this file after meaningful changes. Never infer success from source existence. PASS below applies only to the explicitly named assertions. Do not repeat completed checks without a change, failure, or new coverage reason. The separate unfinished `annomaster-next` port is excluded from this live-app audit.

## Purpose, scope and architecture


Self-hosted team image/video annotation studio producing YOLO training datasets. Live app: Python 3.10+, Flask, SQLAlchemy, SQLite WAL, Jinja, vanilla JavaScript/Canvas, CSS tokens. Thin `app/api` handlers call `app/core`; `app/models` holds users/workspaces/membership/locks/audit/images/batches/assignments. JWT authentication via PyJWT uses Bearer headers or HttpOnly cookies. Owner/editor/viewer workspace roles. SQLite stores identity/tracking; filesystem stores images, confirmed `.txt` labels, suggestion/rejection JSON sidecars, project metadata and version snapshots. `app/core/paths.py` owns path construction. Confirmed-only exports are an invariant; auto-approve mode explicitly confirms model output.

Dependencies: requirements.txt; Flask-Migrate (no migration history directory), Flask-Limiter (memory backend), Pillow, ffmpeg, Ultralytics/YOLO, torch/torchvision, SAM3, timm/DINOv2, OpenAI CLIP. AI inference and email delivery require environment-specific runtime checks. Three.js and fonts load from external CDNs on auth pages; core forms must survive decoration failure. Root frontend has no build step.

Structure: `app/` backend; `templates/` pages; `static/css/` token/theme/page styles; `static/js/main.js` live annotation engine and hash routes; `static/js/features/` auth/workspace/projects/settings/prompt tools; `scripts/` backup, consistency, migrations and audit tools; `docs/` guides. `workspace/`, SQLite files and model weights are live data: do not modify for testing. `static/js/engine/canvas.js` is a stale copy, not the loaded engine.

`annomaster-next/` is an unfinished FastAPI/Postgres/Celery/Redis/React port with its own PORT_PLAN.md. It is inventoried separately by existence only and excluded from live-app modifications. No rewrite or invented training/deployment service is authorized by mere Roboflow parity; focus on annotation/dataset workflows already in scope.

## Evidence and completion definition

Browser automation is now available: installed Chrome controlled by Python Playwright against disposable Flask/SQLite/workspace fixtures. Earlier in-app/native browser policy and loopback failures were real blockers; the user explicitly authorized the Playwright alternative, and approved execution outside the socket-restricted sandbox resolved them. **Browser testing is IN PROGRESS, not blocked or complete.** The user's live workspace/database/server were not used for test mutations.

- Static inventory: **95 route declarations, 13 templates, 489 static controls**. This count includes controls in unused templates and omits some dynamic elements; it is not a tested-control denominator.
- Browser evidence: **175 PASS assertions/workflow groups and 39 OBSERVED inventory records**, across nine phase files. A group may exercise several controls; 175 does not mean 175 pages or complete feature coverage. Of these, 100 are rendering/layout/navigation assertions and 75 are selected functional workflow groups.
- API regression: **41 tests run, 40 PASS, 1 SKIP**, no failures/errors. Windows symlink privilege prevented the skipped escape test; it is not passed.
- Pure live Boxes state checks: **9 PASS**, including explicit Null preservation. Changed JavaScript syntax recheck passes. No frontend compilation step exists; actual Flask boot and browser flows are the runtime checks.
- Python AST: **56 files PASS**. `git diff --check` passes with line-ending notices only. Browser runner exits1 on failed checks and2 on blocked checks, preserving JSON evidence either way.
- Durable structured evidence: `docs/audit-browser-results.json`, `docs/audit-test-results.json`, `docs/audit-lifecycle-results.json`, `docs/audit-javascript-results.json`, `docs/audit-source-inventory.json`.
- Raw screenshots/downloads/control inventories: ignored `.audit-browser/`; reproducible with `scripts/browser_audit.py`. Screenshots cover desktop 1440x900, tablet 768x1024, mobile 390x844. These are viewport checks, not physical-device/touch certification.
- Retained mobile screenshot evidence: `docs/audit-screenshots/{annotate,settings,classes}-mobile.png`. These show the current layouts, including the annotation toolbar limitation, rather than certifying all states.

**Conservative audit completion: 19/80 acceptance gates = 23.75% (24% rounded).** This is a newly defined baseline, not a time estimate or test pass rate. There are 16 distinct page/route states below, each with five gates: render, complete UI/state review, exhaustive interactive controls, complete backend integration/failure coverage, responsive review across states. Partial gates earn zero. Rendering is closed for all 16; Health also closes UI, controls (none), and responsive gates. Other gates remain partial because not every control/state has been covered. Selected workflows passing does not close a whole-page gate. No HTML page has exhaustive control acceptance yet. Overall feature parity with Roboflow is not a measurable percentage at this point.

## Phase status

| Phase | State | Evidence / next work |
|---|---|---|
| 1 Discovery | Initial review complete | Architecture, dependencies, data invariants and live engine identified; migration-trigger deployment behavior still needs a copied-DB test |
| 2 Inventory | Static baseline complete; dynamic inventory partial | 94 declarations, 13 templates, 484 controls; per-page visible-control inventories captured |
| 3 Page UI/UX | In progress | Every accessible entry opened separately at three sizes; screenshots are not exhaustive state acceptance |
| 4 Functional testing | In progress | 67 selected browser workflow groups PASS; advanced controls and permissions pending |
| 5 Roboflow comparison | In progress | Official public upload/version docs checked; authenticated Roboflow platform not accessed |
| 6 Fixes | In progress | Reproduced fixes and bounded retests listed below; known gaps remain |
| 7 Regression | Current selected checks PASS | 37 API tests + 9 state checks; browser phase evidence retained; one environment skip |
| 8 Permanent memory | Current | Resume exact next tasks below; never report audit complete from selected pass counts |

## Page-by-page acceptance checklist

Legend: P = gate closed; PART = partial, not passed; N/A = no interactive UI (closed only where stated). R = rendering, U = UI/UX, C = controls, B = backend integration, M = responsive. Project URLs include `?workspace_id=1&project=audit-project` in fixtures. Expected behavior is usable rendering, working controls, correct persistence/permissions/error states, and reachable layouts at all three sizes. The tested controls and actual results are detailed in the next table.

| Page / route | R | U | C | B | M | Bugs found / fix implemented | Retest / remaining |
|---|---|---|---|---|---|---|---|
| Login `/login` | P | PART | PART | PART | PART | Removed unsupported social/remember promises; favicon and Three.js warning fixed | 7 primary form/theme/scene checks plus links PASS; keyboard/accessibility and CDN failure states pending |
| Register `/register` | P | PART | PART | PART | PART | Invalid email/username acceptance fixed; unsupported links/claims removed | Validation, visibility/strength, real success and duplicate PASS; shared decorations/footer individually pending |
| Reset request `/forgot-password` | P | PART | PART | PART | PART | Honest links/claims | Validation, sent/return PASS; real SMTP delivery blocked by absent configured mail service |
| Reset token `/forgot-password?token=…` | P | PART | PART | PART | PART | Invalid/single-use handling verified | Real valid reset/new login, invalid/used token PASS; explicitly expired token UI pending |
| Dashboard `/` | P | PART | PART | PART | PART | Scoped deletion tracking cleanup fixed | 9 CRUD/navigation groups PASS; cover chooser, account menu, permission and mobile interaction states pending |
| Legacy upload `/pages/upload` | P | PART | PART | PART | PART | Missing canvas crashed main.js; now redirects preserving project context to maintained upload section | Redirect/render PASS; exhaustive destination controls tracked below |
| Project overview `/pages/annotate#projects` | P | PART | PART | PART | PART | Same-document hash navigation fixed | Section activates at all sizes; dynamic project controls pending |
| Project upload `/pages/annotate#upload` | P | PART | PART | PART | PART | Raw-image filter, ignored video format/size, duplicate index omission, obsolete size handler fixed; unsupported video split selection explicitly gated | Real two-image chooser, ZIP import, MP4→2 PNG128x96 frames PASS; folder/drop/corrupt input variants pending |
| Annotation `/pages/annotate#annotate` | P | PART | PART | PART | PART | Null autosave data loss; mobile canvas/grid/header overlap fixed | Mouse box/class confirm/save/reload, Null navigation, modes/zoom/modals, YOLO11n/SAM3 PASS; advanced edit/polygon/locks/touch and toolbar overlap remain |
| Dataset `/pages/annotate#dataset` | P | PART | PART | PART | PART | Dataset-card Export was a toast only; now actual scoped ZIP | Add box+Null batch, search/class filter, scoped download PASS; global Split broken in source, bulk/tag/delete/split controls pending |
| Versions `/pages/annotate#versions` | P | PART | PART | PART | PART | Invalid split, empty-folder download, false-success build failures fixed | Five-step snapshot/create/ZIP/delete PASS; resize/orient/normalize/augment remain metadata-only, not complete |
| Classes `/pages/annotate#classes` | P | PART | PART | PART | PART | Mobile title/form clipped; responsive wrapping and scrollable table implemented | Add/color-event/rename/sync/classes.txt PASS; delete/remap/tag CRUD and actual table scroll pending |
| Settings `/settings` (8 tabs separately visited) | P | PART | PART | PART | PART | Mobile grid, fake 2FA/session entries, 6-vs-8 password hint fixed | 18 workflow groups PASS; real TOTP/revocation absent; bio cross-browser persistence and danger actions pending |
| Members `/workspace/<id>/members` | P | PART | PART | PART | PART | API last-owner guard and scoped cleanup preserved | Invite/duplicate/all role options/remove/reload/navigation PASS; separate viewer/editor browsers and account menu pending |
| Help `/help` | P | PART | PART | PART | PART | Added real data/usage destination for dead footer links | Render/three viewport bounds PASS; every help link interaction and accessibility review pending |
| Health `/health` | P | P | N/A (closed) | PART | P | No fault in healthy disposable fixture | HTTP/browser JSON200 and three viewport bounds PASS; degraded DB/filesystem states pending |

Unregistered `classes.html`, `dataset.html`, `versions.html` stubs were source-inventoried; they are not independent registered pages. Shared navbar/account menu remains a per-host-page audit task. The JSON route inventory lists every API handler; anonymous401 coverage is not authorized-workflow coverage.

## Actual browser interactions and outcomes

| Area | What was tested / expected | Actual / status | Limits |
|---|---|---|---|
| Auth (19 groups) | Empty/wrong/offline login, recovery, password show/hide, theme persistence, scene choice, valid login; login links; registration validation/strength/duplicate/success; reset request/invalid/valid/used | All selected assertions PASS; actual authentication and new-password login succeeded | Deliberate offline/401/409 logged; SMTP mocked in API tests, no delivery claim |
| Dashboard (9 groups) | Search no-match/clear; all sort choices; list/grid; workspace empty/create/rename/switch/delete; project empty/create/rename/duplicate/share/merge/move/delete; nav | Selected controls PASS, confirmed mutations and reload/navigation | Missing-user invite404 is expected validation; covers/account/mobile controls incomplete |
| Settings (18 groups + 8 tab observations) | All tabs, profile save/reload, avatar presets/reset, theme modes/presets/colors, every card dropdown option, opacity, save/reset, notification checkboxes, every language option, density persistence, password validation, workspace rename/invite, defaults and signout | PASS, including corrected runner expectation that absent theme key means default dark | Colors tested by change events, not native OS picker. Languages/preferences persist locally, not proof of translation or notification delivery. Phone is browser-local; bio backend discrepancy remains |
| Project (12 groups) | Six nav buttons, rail collapse; class CRUD subset/export; real images; mouse drag box/class confirmation; saved API state/reload; modes/grid/labels/repeat/zoom; Null next/previous; help/stats/brightness dialogs; batch→dataset; search/class filter; version wizard; downloads/delete | PASS. Dataset includes both box and explicit Null; downloaded ZIP has 2 images/2 labels and no suggestion sidecars | Mode selection is not polygon drawing. Search/filter fields exercised but exhaustive result combinations not verified. Snapshot creation does not prove transforms |
| Members (3 groups) | Required/success/duplicate invite; viewer/editor/owner/viewer selections; removal confirmation/reload; Dashboard/brand links | PASS | Not yet full multi-browser permission/lock acceptance |
| AI (4 groups) | Exact selected YOLO11n inference; invalid .pt rejection; phrase add/remove; text/box tabs/polarity/collapse; SAM3 text inference | PASS. Response explicitly model=yolo11n.pt; SAM3 cuda:0 returned200 (~13.8s in recorded run) | Synthetic images, zero YOLO detections: integration only, not model accuracy. Box-example inference and thresholds/batch actions incomplete |
| Media (2 groups + 1 preview observation) | Actual YOLO ZIP preview/import and annotation load; actual H264 MP4 at2fps, PNG128x96; confirm two batch/index paths, download both and inspect dimensions | PASS after fixes, no media pageerror in final run; identical pixels do not drop retained frame paths | OpenCV fallback, all formats/sizes/error variants and folder/drop flows incomplete |
| Layout probe (45 assertions +30 inventories) | Open each page entry separately, take all three sizes, activate each hash section, test canvas/card bounds and header groups/action bounds | PASS for named assertions; final probe has no console/error/network-failure events | No root overflow is not complete responsive usability. Draw toolbar still crowded on mobile; real touch not exercised |

## Reproduced fixes in this browser continuation

| Issue / initial actual behavior | Files / decision | Verified result |
|---|---|---|
| Legacy upload loaded engine without canvas and crashed | `app/__init__.py`: redirect to maintained section, preserve query | Route and destination open in Chrome |
| Changing hash did not activate the section | `static/js/main.js`: validated hashchange listener | All six sections at three sizes PASS |
| Settings mobile grid overflow/crushed fields | `tokens.css`, `settings.css`: responsive grid tokens | Browser viewport checks and mobile screenshot review PASS; full state layouts still partial |
| Fake six-digit 2FA activation, invented sessions | `settings.js`, settings template: remove simulation, state unavailable, actual browser signout; eight-character hint | Security assertions and signout/restricted-page redirect PASS; no real TOTP claimed |
| Raw annotation menu filtered nonexistent folder field | `main.js`, `uploads.py`: filter confirmed/null paths, return explicit null_paths | Browser raw-batch loading PASS |
| Empty autosave removed explicit Null label | `main.js`: shared Boxes.preservesNull guard across four save paths | Browser Null→previous→dataset roundtrip PASS; ninth pure lifecycle check PASS |
| Completed dataset-card Export did nothing | `main.js`, `datasets.py`: actual selected-dataset download | Browser ZIP download PASS; isolated API test excludes second legacy dataset |
| Video ignored requested PNG/custom dimensions | `uploads.py`: validate FPS/format/size; ffmpeg/OpenCV resize, format-aware indexing | Actual2frames PNG128x96, downloaded dimensions PASS (ffmpeg path) |
| Identical retained frames omitted from index/DB | `db_index.py`, upload callers: explicit keep_duplicate indexes retained paths while preserving default duplicate detection | Both frame paths present; API retained-duplicate regression PASS |
| Video size dropdown threw app.onSizeChange missing | Annotation template: remove obsolete inline handler; existing event listener retained | Browser media rerun PASS with no pageerror |
| Favicon404 and Three.js nonindexed conversion warning | New own SVG/favicon route; remove redundant conversion | Final page probe has no logged console/network failures |
| Mobile Classes header/form clipped | Token-based wrap/padding; scrollable table | Screenshot review and render PASS; all table interaction pending |
| Mobile canvas unavailable; collapsed sidebar kept grid track | minmax grid, explicit collapse class, responsive auto-collapse, empty card bounds | Canvas/card fits all three sizes; screenshot reviewed |
| Header controls overlapped on small screens | Responsive header rows/height/wrapping via tokens, shared toolbar offsets | Header groups/action bounds PASS at all3 sizes; screenshot reviewed |

Runner failures due to selectors (icon accessible names, menuitem roles, merge label) and reset-default theme assertion were corrected as test-harness errors, not counted as application defects. Initial custom-model response capture was replaced with a request/model-specific YOLO11n assertion. Bad fixture class hex was corrected to RGB without changing the production class contract.

## Prior completed fixes (preserve)


1. Shared path containment on media/annotations/null/locks/AI/cover and dataset image deletion; malformed paths rejected.
2. Null POST/DELETE respect another editor's active lock; slash normalization.
3. Invalid label payload rejected before replacing saved annotations; polygons/IDs/finite unit coordinates validated.
4. Malformed authentication JSON returns 400.

Files changed before this full audit: app/core/{paths,yolo}.py, app/api/{media,annotations,locks,auth,projects,ai_annotate,datasets}.py, tests/test_review.py, CLAUDE.md, docs/README.md and the dated review/maintenance guides. Existing tests cover those fixes; Windows symlink privilege limitation remains.

## Earlier audit fixes and preserved regression coverage

- Registration/profile input validation rejects invalid email/overlong username before partial mutation.
- Project/workspace/sole-owner account deletion cleans scoped tracking; project filesystem failure preserves tracking; neighboring projects are preserved. Historical audit records intentionally remain.
- Version build failure returns error without publishing metadata; empty/stale/outside folder paths cannot download working directory; split ratios validated.
- Legacy ZIP export includes paired confirmed .txt only, preserves sparse IDs, excludes suggestion/rejection JSON.
- Auth placeholder social/remember/compliance/metrics promises removed; real help/data/usage links added.

These fixes are API-regression verified. Mocked disk-full/SMTP checks are not real hardware/mail delivery tests.

## Browser console, network and API review

Final layout probe logs no console/pageerror/request failures. Final media phase logs no pageerror after size-handler fix. Deliberate validation responses remain in evidence: wrong password401, duplicate account/member409, missing invitee404, corrupt model422, injected offline login failure. Navigation-triggered net::ERR_ABORTED requests (workspace refresh/lock release/logout etc.) are recorded, not counted as successful responses; potential races still need targeted review. No claim of zero errors across all untested states. HTTP200 alone is not model accuracy, transformed-version correctness, or permission acceptance.

## Roboflow comparison and scope

Official public references checked 13 November2026: [uploads](https://docs.roboflow.com/datasets/create-and-upload/adding-data), [dataset versions](https://docs.roboflow.com/datasets/versions/dataset-versions), [platform](https://roboflow.com/). No authenticated Roboflow account was used. No proprietary source/assets copied.

The official upload workflow groups image/video/annotation intake under a Project, including frame sampling and annotation imports. Our tested project upload→batch→annotation path now works for selected image/YOLO ZIP/MP4 fixtures. Folder/drop, retry/corrupt inputs, richer import formats, cloud sources and camera capture are not complete parity claims. Broader formats/cloud capture require scope decisions rather than silent feature promises.

Roboflow documents versions as snapshots that can apply preprocessing and augmentation. This app exports real snapshots, but transformation options are still metadata-only: a material relevant gap, not a verified implementation. Teams/roles exist but full frontend permission flows remain partial. Managed training, hosted deployment and model evaluation are not implemented services in this annotation app; do not invent working status or dead buttons for them. Developer/API guidance and analytics UI remain incomplete.

## Unresolved bugs, limitations, blockers and exact next tasks

1. **Next task: remaining Annotate controls in docs/annotate-control-checklist.md.** Global Split now works for reviewed indexed DB images with JSON/ratio/role tests. Legacy folder splitting remains unsupported with an explicit error. Continue long queue filters/pagination, resizers/touch, editor project/account menus and real multiuser conflict tests; do not repeat completed checks without reason.
2. Version preprocessing/augmentation is metadata-only. Implement image+label transforms with geometry/EXIF tests or visibly gate unsupported choices. Do not mark wizard transforms as complete from ZIP creation. Mid-build partial-folder cleanup also needs review.
3. Continue actual canvas control ledger: polygon draw/edit/resize, undo/redo, copy/paste/delete, nested boxes, notes/properties/raw tabs, shortcuts, complete/save/autosave conflict states, class delete/remap, multiuser lock expiry/force-release. Mobile drawing toolbar remains crowded/overlapped; make its controls reachable and test touch/pointer layouts with loaded images and open panels.
4. Batch tags/assignment/edit/delete, dataset bulk remove/move/split/review/tags, all filters/pagination and populated/empty/error states remain partial. Verify duplicate export basenames across batches, sparse IDs and Null labels across every source.
5. Dashboard cover chooser/upload, account menus/shared navbar, mobile sidebar/keyboard/focus, every modal cancel/backdrop/Escape, and project selector/new/delete inside editor remain incomplete.
6. Settings bio is currently browser-local despite backend bio support; reproduce in a new browser context and persist through API. Phone/avatar/preferences are local; label scope clearly. Test account/workspace deletion via Settings, successful password change UI and all validation combinations. Language selection persistence does not prove translations. TOTP, real notification delivery and remote token revocation are absent, explicitly not claimed working.
7. Separate viewer/editor/owner browser contexts must verify every visible mutation/permission, last-owner handling, invitation routes and account menus. API guards alone do not establish UX correctness.
8. Upload folder chooser/drag/drop, corrupt ZIP/video, invalid format/size/FPS server cases, duplicate imports, cancellation/retry/limits, OpenCV fallback and multiple video formats remain untested variants.
9. AI exemplar creation/deletion/inference, threshold/class mappings, suggestion acceptance/rejection across browser reload and inference failures remain partial. Synthetic-image integration is not detection quality or accuracy evaluation.
10. Real SMTP delivery blocked by unavailable configured mail service; Windows symlink test blocked by OS privilege. Native OS color picker, physical devices/touch, Safari/Firefox, live production migrations and real disk failures are not verified. Browser automation itself is now available.
11. Help/footer links on every source page, auth shared controls individually, expired-token UI, keyboard/accessibility, loading/error states, degraded Health and CDN failure behavior need dedicated checks.

## Files changed and reproducibility

Browser-continuation changes: `app/__init__.py`, `app/api/{uploads,datasets}.py`, `app/core/db_index.py`; `static/js/main.js`, `static/js/features/{settings,auth-scene}.js`; `static/css/{tokens,main,settings,annotate-v2}.css`; `templates/pages/{annotate,settings}.html`; own `static/favicon.svg`; `tests/test_audit_workflows.py`; `scripts/{browser_audit,audit_server,summarize_browser_audit}.py`, `scripts/audit-requirements.txt`, `scripts/test_annotation_lifecycle.cjs`; `.gitignore`; docs and structured results. Earlier fixes also touched auth/projects/workspace/versions/path/label/lock modules and new `app/utils/data_cleanup.py`; preserve them.

Run `python scripts/run_audit_tests.py`; `node scripts/test_annotation_lifecycle.cjs` (Node runtime required); `python scripts/audit_inventory.py`. Install isolated browser dependencies using `python -m pip install --target .audit-tools -r scripts/audit-requirements.txt`. Run `python scripts/browser_audit.py PHASE` sequentially for probe/auth/dashboard/settings/project/members/ai/media; see `docs/testing-and-maintenance.md`. Each owns a disposable server and refuses an occupied port; never stop the user's server. Refresh durable evidence with `python scripts/summarize_browser_audit.py`. No production build step exists in root Flask frontend. `annomaster-next` was not built or tested.

## Every route and control inventory

`docs/audit-source-inventory.json` is the authoritative regenerated list of all95 route declarations, handlers,13 templates and484 static controls. `docs/audit-browser-results.json` adds per-page dynamic visible-control inventories plus actual phase assertions/network events. Static controls retain untested status unless a named browser/API check above supplies bounded evidence. Dynamic menus and permission states are not fully enumerated. Consult these artifacts together; do not convert source inventory or anonymous401 coverage into a pass claim.

## Password-reset delivery follow-up (13 November 2026)

User reported no reset email. Read-only configuration inspection found no root .env and no MAIL_SERVER/MAIL_USERNAME/MAIL_PASSWORD/MAIL_FROM in this session. Previous verification covered reset tokens and mocked delivery, not inbox receipt. Existing code logged links without SMTP while returning an on-its-way message. The API now checks server/sender before account lookup and returns the same503 mail_not_configured error for known/unknown addresses; frontend displays it instead of the sent view. Regression test confirms no sender call, no account enumeration. API suite:38 run,37 pass,1 OS-privilege skip. Gmail SMTP setup added to docs/installation.md and .env.example clarified. Actual delivery remains BLOCKED pending locally supplied sender credentials; no email was sent or inbox delivery claimed. Gmail is an SMTP provider; recommend it for the current small installation. Real Chrome auth retest:19 groups PASS, including visible unconfigured-service error, hidden sent view, re-enabled submit, and valid-token password reset. Refreshed auth evidence retained. SMTP runtime failures still log asynchronously and do not provide per-message delivery confirmation. Overall acceptance remains19/80 (24%).

Local mail setup assistance: created Git-ignored root .env with Gmail SMTP host587/STARTTLS and localhost base URL. MAIL_USERNAME, MAIL_FROM and MAIL_PASSWORD intentionally remain empty for the user to enter locally. No keys/database settings overwritten; no email sent. Actual delivery remains unverified until credentials are configured and the app restarted.

## Dataset image-gallery improvement (13 November 2026)

User requested the Dataset page at /pages/annotate?workspace_id=1&project=m#dataset to feel like Roboflow's image browsing page. Implemented in the shared live Flask page, without touching project m data. Reference: official https://docs.roboflow.com/llms.txt identifies dataset-search and image-management workflows; no authenticated Roboflow account/source/assets used. Specific dataset-search content was inaccessible through the web tool; do not claim pixel-level parity or access to the authenticated product.

Changes: new scoped static/css/dataset.css, loaded after existing sheets; compact Dataset-only project/account header; heading and image count; responsive full-image gallery with contain sizing instead of crop/hover zoom; Small/Medium/Large thumbnail density; annotation overlay toggle; Select page, accessible selection buttons and keyboard image opening; clearer split/status/background labels; filtered-empty versus genuinely empty states and context action; actionable load error/Retry; Create version shortcut. Existing image viewer, annotation edit, export and backend persistence preserved. Incomplete global Split action was replaced on this page with the working version entry point; global Split elsewhere remains an unresolved task, not fixed here.

Functional fixes: search debounce/AbortController prevent stale responses overwriting newer filters; no duplicate dsEmpty IDs after network errors; selected cards identified by full path, not filename/suffix; Ctrl+A no longer steals input selection; escaped gallery filenames/paths; correct letterboxed overlay geometry with cached per-thumbnail annotations and ResizeObserver redraw; background class filter now actually filters is_null; val/valid filter aliases match both sources; initial page size50 now exists in selector; page-specific labeled count explicitly says it is for this page; Create version first-visit listener race fixed by invoking existing wizard directly. No database schema change.

Tests: final project Chrome phase14 groups PASS, including new comprehensive gallery group and deliberate network-failure/Retry group. Interacted with all split choices, class/background filters, search no-match/reset, density choices, label toggle, select-page/clear/single selection, keyboard opening, next image, close, page-size20/50, Create version open/close. Real thumbnail image loads and existing mouse annotation/Null/dataset/version/export roundtrip passed. Viewports1440x900,768x1024,390x844: no root horizontal overflow; card bounds fit; screenshot review completed. Final project log has no pageerror; intentional request abort is retained as failure-path evidence, not a production API success. API39 run:38pass,1symlink privilege skip; added focused background/validation split test. main.js V8 syntax PASS. Plain status-label wording refined after the interaction run; selectors/behavior unchanged.

Evidence: docs/audit-browser-results.json (project phase), docs/audit-test-results.json; retained docs/audit-screenshots/dataset-gallery-desktop.png and dataset-gallery-mobile.png (disposable synthetic green/blue fixture images, not user data). Raw tablet/gallery/headers in .audit-browser. Screenshots precede final Labeled/Unlabeled/Valid wording only.

Remaining: no claim of full Roboflow parity or exhaustive Dataset acceptance; bulk deletion/reannotation permission/concurrency, large-dataset performance, full pagination, touch and all viewer states still need dedicated checks. Live project m was not authenticated/interacted with during this change. Overall formal audit remains19/80 gates (24%) until full-state acceptance criteria are met. Continue the existing unresolved-task list; user prioritized this gallery ahead of global Split.

## Dataset light-mode correction (13 November 2026)

User reported dark controls remaining in Dataset light mode. Reproduced in real Chrome: class dropdown and per-page dropdown used hardcoded rgba(10,10,18,.95), sidebar/account avatar intentionally retained dark brand surfaces, and viewer backdrop/body/shadow used fixed black. Previous gallery testing was primarily dark mode; page-background assertions alone did not cover component surfaces and were insufficient.

Fixed main.css dropdown backgrounds to semantic surface tokens; viewer backdrop/body/shadow now use overlay/bg/shadow tokens. Dataset-scoped dataset.css now themes the rail and its foreground through semantic aliases, removes heavy rail shadow, makes account trigger/avatar theme-aware, and fixes selection/status badges over thumbnails. Other annotation-page rail styling is preserved outside Dataset. Light theme no longer intentionally retains a dark Dataset rail. Source image pixels are not recolored.

Added actual Chrome light/dark theme phase inside project regression: screenshots at1440x900,768x1024,390x844, plus image-viewer screenshots in each mode. Records computed colors for page/header/filter/card/toolbar/search/size/class/per-page/rail/account controls. Asserts light backgrounds on class/per-page/rail/account individually, rather than page background alone. Allows350ms for CSS transitions before screenshots. First component-check run passed15 project workflow groups with no failures; final screenshot refresh follows. No backend logic changed in this correction; previous API39-test baseline still applies. Live project m data not mutated. Overall full-app acceptance remains24%, not a full theme/accessibility certification.

Final theme retest:15/15 project browser groups PASS; light and dark gallery/viewer screenshots reviewed, with no project pageerror. Durable evidence refreshed, including docs/audit-screenshots/dataset-light-{desktop,mobile,viewer}.png.

## Annotation-only status footer (13 November 2026)

User reported Draw/Saved/image/cursor/zoom footer leaking into Dataset and other sections. Root cause: footer is outside individual page containers in the shared annotation template, so changing active page did not hide it. Added scoped CSS in main.css: when page-annotate is not active, hide .status-bar and set inherited --sb-h to0. Other sections reclaim the footer space instead of leaving an empty strip; annotation mode keeps its normal footer/height. No annotation save logic changed. Browser probe now asserts hidden footer and full-height page bounds on Projects/Upload/Dataset/Versions/Classes, visible footer on Annotate, at all three existing viewport sizes. Final result recorded below after probe completion. Full-app acceptance remains partial.

Footer regression also exposed Upload's height:100% overriding its fixed top/bottom bounds and extending the page below the viewport. Changed only #page-upload height to auto in upload.css; fixed offsets now define available height. Initial test failures retained as discovered layout issue, not passed. Final probe rerun pending result below.

Final footer probe:93 records,63PASS assertions and30OBSERVED inventories, no failures. All18 section/viewport footer checks PASS; Upload bounds corrected. Durable browser evidence refreshed.

## Annotate UI/theme and interaction follow-up (13 November 2026)

User prioritized /pages/annotate#annotate. Used isolated Chrome fixtures, never modifying live project m. Added actual light/dark screenshots with a loaded labeled image at1440x900,768x1024,390x844; exercised toolbar scroll access to Box/Polygon/Select/Pan/Labels/Undo/Null and asserted button bounds. Light rail background checked explicitly. Reproduced polygon undo failure: normal class-popup polygon creation did not push history; _finishPolygon now captures history before opening the picker, matching box-drawing behavior. Real three-point polygon, class confirmation, Undo/Redo/Undo passed. Existing box draw/save/reload, next/Null/previous, mode/view/zoom toggles, dialogs, dataset/version/archive regression still passed in the16-group run.

UI changes: annotation-scoped rail/account colors use selected theme; narrow drawing toolbar has bounded width with horizontal scrolling and nonshrinking groups; toasts use semantic surface instead of fixed black and stack height is limited to prevent a series of toggles covering the entire image; mobile/tablet bottom image navigation moved above zoom controls to avoid overlap. No image colors changed. Files: static/css/{main,annotate-v2}.css, static/js/main.js, scripts/browser_audit.py. Backend regression39 tests:38PASS,1Windows symlink skip. Full app/page acceptance still PARTIAL: advanced move/resize/delete, per-tab content, complete/save failure states, multiuser permissions/conflicts, physical touch and all AI variants remain unfinished. Existing AI integration evidence is from earlier phase, not a new accuracy test. Overall formal completion remains24%.

Final rerun adds explicit non-overlap assertion for mobile/tablet navigation and zoom; outcome appended below. Screenshots/evidence refreshed after success. Follow up on cancel-picker history semantics and annotation metadata counters (header/card dot can lag saved state); do not claim these fully verified.

Final Annotate regression16/16 groups PASS, including explicit mobile zoom/navigation non-overlap, polygon history and both themes at three sizes. Browser evidence refreshed; retained annotation-light-desktop.png and annotation-dark-mobile.png under docs/audit-screenshots.

## View-toggle popup verification (13 November 2026)

User specifically reported dark popups from View group (Labels/Grid/Repeat). Previous screenshot checks let notifications expire and did not directly assert their appearance; that was a coverage gap. Added explicit clicks of each toggle in light and dark modes, assert each visible popup background (light channels>200/dark<100), screenshot while open, close with X, and restore toggle state. Toast-specific #toastStack .toast background/text rule added to annotator stylesheet to preserve theme under cascade overrides. Versioned main/annotate-v2 stylesheet URLs to invalidate previously cached dark styles. Existing semantic toast CSS was already present; do not claim that a new root cause on the user's running server was observed without live authenticated evidence. Browser regression outcome follows; user's project untouched.

Final View-popup test: all three Labels/Grid/Repeat popups asserted visible with light backgrounds in light mode and dark backgrounds in dark mode; close controls exercised;16/16 project workflow groups PASS. Popup screenshots capture opening animation, so computed-color assertions are the decisive appearance evidence. Added stylesheet cache-busting URLs so a normal page reload fetches corrected CSS. No claim that user's running browser has refreshed until they reload.

## AI panel navigation lifecycle (13 November 2026)

User reported Smart Detect/AI Annotate remaining visible after leaving Annotate. Previous tests covered panel open/close but not leaving with panels open; coverage gap acknowledged. showPage now invokes each visible panel's existing close button before leaving Annotate, preserving its own mode/overlay/transient-state cleanup. CSS additionally hides sdBar/paBar when Annotate is not active to guard visual leakage from late async updates. No inference cancellation/accuracy guarantee added; already-running server inference is not claimed cancelled. Added real Chrome regression opening each panel, visiting Dataset/Versions/Classes/Upload/Projects, asserting both panels hidden, returning to Annotate and asserting closed state, plus direct hash navigation. Actual result appended after execution. User's project unchanged; full audit remains partial.

Final AI navigation regression17/17 project workflow groups PASS. All10 panel/destination combinations plus hash navigation verified; durable browser evidence refreshed. Versioned main.js/annotator CSS URLs force updated assets on page reload. No full-page/full-app completeness claim.

## Expanded Annotate control audit and permanent checklist (13 November 2026)

User requested proactive full Annotate UI/UX, every control/popup/navigation, both themes, responsive checks, fixes and durable memory. Created docs/annotate-control-checklist.md with per-control groups, explicit expected/actual bounded passes, pending cases, and required future test matrix. CLAUDE.md now directs future Annotate work to read it. Do not claim full page acceptance: editor project/account controls, long filtered queues, resizer/touch, inline dataset panel and real multiuser conflict states remain pending. Latest tests substantially expand coverage but do not satisfy every matrix cell.

New fixes this batch:
- Current-image saves check HTTP/errors before showing Saved. Save409 test now shows Error; retry succeeds. Done previously only changed a browser flag: now awaits persistence, refuses failed saves/no annotation unless Null, advances only on success, and preserves Null labels. Header navigation uses shared queue-aware next/previous helpers.
- Properties clamps X/Y/W/H to image boundaries, refreshes fields/list, and transforms polygon vertices with its changed bounds. Cancelled polygon picker no longer pushes a history step; confirmation does.
- Regular annotation dialogs and class picker close when leaving Annotate, not only AI panels. Escape now includes Settings/Stats and guards missing modal elements. Existing modal backdrops intentionally block sidebar clicks; hash navigation tests leaving while modal is open. Initial runner failure attempting a click through a modal was a test issue, not an app defect.
- Raw Copy exports confirmed annotations only, handles clipboard rejection, and includes a fallback for insecure contexts. Real Chrome clipboard readback passes on loopback; physical LAN/insecure clipboard still unverified.
- Notes render user text safely rather than injecting markup. Existing notes are session-only and now explicitly labeled not synced; durable notes remain missing, not silently claimed implemented.
- Repaired global Split contract: new role-checked JSON POST /split updates reviewed indexed image metadata without moving files; frontend no longer parses /export ZIP as JSON, and zero ratios remain zero. Invalid ratios400 and viewer403 covered. Canonical DB validation split is valid; add-to-dataset writes valid and export normalizes legacy val. Split action does not mutate legacy folder datasets, and no-reviewed input reports an explicit error. Media responses overlay central split metadata so refreshed controls see it.
- Windows slash mismatch prevented successful label/Null saves updating central Image reviewed flags. Queries now normalize stored rel_path for all three annotation/Null tracking updates. New API test covers backslash row + forward-slash save and Null.

New browser sweep in light AND dark: select annotation via list; Properties tab/oversized input/Apply/undo; class switch0→1→0; Set cover; Delete/undo; Raw tab and actual clipboard; Notes add/clear and literal markup safety; Help/Settings/Stats/Import/Split open/Escape/reopen/hash leave/return; injected409 save Error/retry Saved; Done refuses save conflict and completes after success; visible Autosave switch; real all-train split including zero val/test; Null Done preserves label. Dedicated class-picker search/no-match/new class/cancel runs both themes. Existing three-size loaded-image/toolbar/popups and dataset/export regressions retained. Last completed sweep19/19 groups PASS before final polygon-geometry recheck, outcome appended below.

Backend regression41 run:40PASS,1Windows symlink privilege skip. Checks include new split role/ratio/canonical value, media split visibility and Windows tracking regressions. No live project m mutations. Initial failures and reasons: modal backdrop selector, hidden native checkbox (corrected to actual visible label), and real reviewed-state path mismatch (fixed). Runner failure cleanup now recognizes .modal-x and console output escapes unsupported Windows characters instead of crashing.

Files: static/js/main.js; templates/pages/annotate.html; app/api/{annotations,datasets,media}.py; app/core/datasets.py; tests/test_audit_workflows.py; scripts/browser_audit.py; docs/annotate-control-checklist.md; CLAUDE.md; permanent and structured evidence. No schema migration. Root frontend has no build step. Full-app acceptance remains19/80 (24%); source inventory now95 route declarations,13 templates,489 static controls. Remaining next steps are in the control checklist; do not repeat named passing checks without a change/new coverage reason.

Final polygon property regression reproduced stale/empty Properties after draw: tab activation did not refresh selected-object form. Added _updateProps on entering Properties. Actual polygon width editing now verifies vertex span70px and undo restoration. Prior failing rerun and cascading tests are not passes; final rerun outcome follows. Required continuation: read docs/annotate-control-checklist.md alongside this file; keep pending matrix cells explicit.

Final expanded rerun19/19 project workflow groups PASS, no failures. Backend41 tests:40PASS,1OS symlink skip. main.js V8 syntax PASS. Durable browser evidence refreshed. Full Annotate acceptance remains PARTIAL; specific pending controls/states are in docs/annotate-control-checklist.md, not delegated back to the user to discover.

## Compact Assign Class picker (13 November 2026)

User reported the picker covering the newly drawn object and being too large. Replaced pointer-release anchoring in _showClassPopup with screen-space annotation-bounds placement: candidates right/left/below/above and canvas corners are clamped inside the canvas and ranked by overlap with the pending annotation. This minimizes overlap; zero overlap is not promised when an object fills all available space. Header supports pointer drag with clamping so user can reposition the picker. Width reduced264→220px (responsive max width), maximum height300px, list capped132px with scrolling, tighter rows/footer, shortened accessible search placeholder. Confirm/Cancel/add-class/keyboard behavior preserved. Footer uses semantic panel color rather than a black overlay. Own implementation, no proprietary Roboflow assets.

Browser test class-picker-compact-nonoverlap-drag-six-theme-viewports draws a real new box in light/dark at1440x900,768x1024,390x844; checks popup bounds, width<=221, zero overlap with the tested box, actual header drag movement, Cancel preserving original annotations, and screenshots while open. All6 combinations PASS. Final project regression20/20 groups PASS including existing picker CRUD, drawing, polygon properties/history, save failures, completion, dataset/version/export. Placeholder wording refined after screenshot run only; no selector/behavior change. Full-canvas objects, very long class lists and every corner/zoom/pan configuration are not exhaustively verified.

Test also reproduced mobile Add to Dataset pill overlapping zoom after reviewed metadata started updating correctly; moved pill above navigator/zoom and prevented collapsed right sidebar intercepting pointer events. The test now waits for transient class-added notifications before attempting unrelated placement checks. Retained screenshots docs/audit-screenshots/assign-class-light-{desktop,mobile}.png. Scripts/CSS URLs versioned for reload. No backend/schema changes this batch; previous41-test baseline applies. Full app/page audit still partial; continue docs/annotate-control-checklist.md.

## Universal shared project sidebar theme and contrast (13 November 2026)

User reported unreadable text on green badges and that sidebar theming was limited to Annotate/Dataset. Replaced fixed-dark compatibility aliases with semantic surface/foreground aliases in shared annotate-v2.css; removed page-specific rail aliases. All six sections using the same navigation (Upload, Annotate, Dataset, Versions, Classes, Projects) now inherit the selected light/dark theme. Badge text uses --on-fill against the accent, not the sidebar foreground (dark-on-green light-mode text was insufficient contrast). Shared avatar and account-dropdown avatar also use accent/on-fill. Inactive navigation uses primary text instead of the dim foreground that failed dark-mode contrast. No approved picker behavior changed.

New scripts/browser_audit.py nav-theme phase: actual navigation through all6 sections in both themes at1440x900,768x1024,390x844; checks rail brightness and computed label/badge foreground contrast>=4.5 against sidebar/accent backgrounds, plus theme persistence after reload. Initial dark inactive-label failures were reproduced and fixed; final37/37 checks PASS. This is bounded default light/dark computed-color evidence, not a full accessibility/custom-accent certification. Source user-specific custom themes not exhaustively tested. Standalone dashboard/settings/auth pages use their own layouts; this result covers the shared six-section project sidebar, not every unrelated component. No backend change or live project mutation.

Evidence refreshed in docs/audit-browser-results.json (nav-theme). Retained docs/audit-screenshots/shared-nav-{light,dark}-desktop.png. CLAUDE.md records universal shared-navigation policy and contrast requirements; CSS URL versioned to avoid stale stylesheet cache. Full application audit remains partial. Sidebar color/style rules must remain shared, not be reintroduced separately per page.

## User-requested undo — recent branding/typography migration

User requested undo of the interrupted purple accent/shared font-theme changes. Removed design-config.css and its import, reversed generated font-size scaling and font-family/color rewrites, restored prior light/dark accent palettes and Settings defaults, and removed recent ThemeEngine contrast/default-accent additions. Earlier approved Assign Class, shared sidebar, annotation/data fixes remain. JavaScript syntax rechecked. Media Library redesign from the preceding request is still in progress and not newly marked passed. Do not reapply purple or central typography migration without a new user request.

## Centralized design system (13 November 2026)

User request: one central place to change colours, fonts, sizes, spacing, buttons, cards and other shared styles for every page, applied to all pages, tested and documented. The existing teal/green palette was kept (the earlier purple re-brand had been undone at the user's request). Reference: `DESIGN_SYSTEM.md`.

**Architecture implemented**
- `templates/layout/head_assets.html`: one `<head>` partial for all 8 rendered templates (fonts, Font Awesome, tokens → base → components → page sheets → modes, `theme.js`, `core/ui.js`). `asset()` Jinja global (`app/__init__.py`) adds `?v=<mtime>` cache-busting; hand-written `?v=` strings removed.
- `tokens.css`: `--font-scale` knob; size steps `--fs-8 … --fs-56` (rem × scale); typography role tokens (`--text-page-title`, `--text-body`, `--text-button`, …); component knobs (`--btn-*`, `--input-*`, `--modal-*`, `--badge-radius`, `--table-row-h`, `--tab-h`, `--tooltip-*`); page tokens (`--page-pad`, `--section-gap`, `--grid-gap`, `--content-prose`); `--purple-bg/-br`, `--on-purple`.
- `components.css` (new): primitives moved out of `base.css` unchanged in cascade position, now token-driven; new `ui-` components: page header, breadcrumb, section title, search field, table, tabs, tooltip, alert, error state, spinner, toast, confirm body. `static/js/core/ui.js` (new): `UI.toast`, `UI.confirm`, `UI.tabs`.
- Fonts: 199 font-family literals replaced by `var(--font-sans/--font-mono)`; auth pages moved from Inter to the app font; Help now actually loads the web fonts; the six canvas `ctx.font` strings (which named an unloaded `'Outfit'`) read `ThemeColors.get().font`.
- Sizes: every px/rem font size ≥8px now uses a step. 90 off-scale values were snapped to the nearest step (ties down; almost all ≤0.5px; largest were auth 19→18 and 25→24, and a 52→48px glyph). Dashboard `--dsh-fs-*` handoff sizes mapped onto the scale. Four sub-8px glyph sizes were kept literal.
- Guard: `scripts/check_design_tokens.py` (0 violations) + `tests/test_design_system.py` (5 tests, in the unittest suite). Deliberate exceptions are fenced with `ds-allow-start: <reason>` comments (auth brand palette, Settings preview/accent swatches, photo checkbox, avatar hue text, toggle knob, iOS 16px).

**Bugs found and fixed**
- Settings read the per-user theme key before the global one (`theme.js` does the opposite) and re-applied it on every visit, writing both keys. This flipped the whole app back to a stale theme and showed an "Interface mode → DARK" toast each time. Now uses the same precedence for the 13 theme/card keys, and applies the saved mode silently on load.
- `upload.css` hardcoded the light theme's accent green in 18 washes; white text on the bright dark-theme accent (~1.6:1); white text on 20% purple washes (unreadable in light); `--up-on-secondary` fixed white. All now use tokens.
- `main.css`: 70 dark-theme-only literals (warning/purple/info washes, dark surfaces, Smart Detect amber text at ~1.7:1 on white, slate text, a forbidden colour fallback) mapped to tokens.
- `modes.css` (custom mode): 11 forbidden `var(--x, #hex)` fallbacks; a custom-mode-only dark navy project rail (contrary to the shared-navigation rule); accent/status literals that ignored the user's colours; white cards and black text that assumed a light custom palette. All mapped to tokens. 6 dead `.auth-left`/`.social-btn` rules removed.
- Settings: an unclosed `.color-picker-container` nested the whole Card Customization section inside the accent card (fixed). ~60 inline styles replaced by `.st-*` classes (their white-wash panels were invisible in light mode). Checkmark `#000` on the accent fill → `--on-fill`. `.btn-danger-solid` white → `--on-fill`. Dead simulated-2FA/QR CSS removed.
- Duplicated toasts (settings.js, which used `innerHTML`, and projects.js) now use `UI.toast`. Native `confirm()`/`alert()` on Dashboard, Members and Settings replaced with the themed `UI.confirm`/`UI.toast`. The type-the-name workspace-delete `prompt()` stays native. `main.js` dialogs and toasts are unchanged (approved annotator behaviour).
- Members title used an inline 22px override; it now uses `.ui-page-title` (24px role).

**Testing (real Chrome, disposable fixture; live project `m` untouched)**
- New `ds-snapshots` phase: 14 pages × light/dark × 1440/768/390 = 84 screenshots. Two baseline runs were pixel-identical (84/84). Before→after diffs are all reviewed and intended: font change on auth/Help, snapped sizes, Settings light theme now correct. Retained `docs/audit-design-snapshot-diff.json`, `docs/audit-screenshots/ds-{settings-light,login-dark}-desktop.png`.
- New `ds-propagation` phase: overrides only `--font-sans`, `--font-scale`, `--accent` and asserts that every page follows. Before: 8/28 PASS (auth pinned to Inter; all six project sections had Sora-literal controls). After: **28/28 PASS**; `--font-scale` resized all sampled elements on every page (Dashboard 17/40 until its aliases were mapped, then 40/40).
- Existing phases on final code: auth 19/19, dashboard 9/9, settings 18/18, members 3/3, nav-theme 37/37 PASS; probe 44 PASS / 1 FAIL; project 19 PASS / 2 FAIL.
- The settings theme test previously "reset" the theme via a native `confirm()` that Playwright auto-dismisses, so the reset never ran. It now accepts the themed dialog and asserts that opacity returns to 1. 4 dashboard/members/settings tests now confirm through `ui_confirm()`.
- **Remaining FAILs, pre-existing:** `annotate-mobile-canvas-accessible` and `media-library-search-clear-sections-collapse-six-theme-viewports`. The canvas area is 26px wide at 390px, and the before-change baseline screenshot shows the same collapse. `class-picker-compact-nonoverlap-drag-six-theme-viewports` fails with "expected to be visible"; likely the same cause, not separately confirmed.
- Unit suite 46 run: 45 PASS, 1 Windows symlink SKIP. `node` lifecycle checks were not re-run (Node isn't on PATH in this session). main.js syntax is evidenced by no project-phase pageerror.

**Not done / limits:** custom-colour mode and compact density weren't visually snapshot-tested (only default light/dark). The annotate template keeps ~165 inline layout styles (now token-only, no colour or font literals). `main.js` still uses native `confirm()` in the annotator. Black-alpha shadows weren't unified onto `--sh-*`. Dashboard radii (`--dsh-r-*`) stay handoff literals. No Model training/deployment/Analytics pages exist, so none were migrated. `templates/pages/upload.html` is unrendered legacy and was not migrated.

**Next tasks:** (1) fix the Annotate mobile canvas collapse (Media Library panel width at ≤639px), then re-run `probe` and `project`; (2) snapshot custom/compact modes; (3) move `main.js` confirms to `UI.confirm` with matching test updates; (4) continue `docs/annotate-control-checklist.md`.

**Files:** new `DESIGN_SYSTEM.md`, `templates/layout/head_assets.html`, `static/css/components.css`, `static/js/core/ui.js`, `scripts/{check_design_tokens,tokenize_typography,compare_design_snapshots}.py`, `tests/test_design_system.py`. Modified `app/__init__.py`, all 8 rendered templates, `static/css/{tokens,base,main,upload,annotate-v2,dashboard,dataset,layout,media-library,modes,settings,help,auth-3d}.css`, `static/js/main.js` (canvas font only), `static/js/features/{settings,projects,workspace}.js`, `scripts/browser_audit.py`, `CLAUDE.md`, `docs/README.md`, evidence JSON. No backend data/schema change. Overall formal acceptance stays at 19/80 gates: this work closes no whole-page gate.

## Classes page polish and verification — 14 November 2026

Route: `/pages/annotate?workspace_id=<id>&project=<name>#classes`.
User requested modern class management matching the app, with direct name editing.
Built on the existing inline-rename implementation; retained the shared Sora typography,
teal/green theme tokens, server class IDs, and existing API behavior. Public reference:
https://roboflow.com/blog/advanced-ontology-management (class management/renaming;
no authenticated Roboflow UI or proprietary assets copied).

Changes in this continuation:
- Compact project/account header on Classes; drawing/save/annotation navigation controls
  are hidden here and restored when navigating to Annotate.
- Desktop/tablet retain the compact class table. Mobile uses readable card rows with
  full wrapping names, ID, annotation count AND image count; actions stay reachable.
- Persistent pencil affordance, clearer delete icon, larger mobile color/delete targets.
- Help explains click-to-edit, Enter or blur to save, Escape to cancel. Existing
  validation and server error behavior preserved and retested.
- All colors/fonts/spacing follow shared tokens; no palette replacement.

| Page / scope | Rendering / UI | Interactive controls | Backend | Responsive | Retest |
|---|---|---|---|---|---|
| Classes `#classes` | PASS for reviewed light/dark screenshots | PASS for add, duplicate, rename Enter/Escape/blur, empty/duplicate errors, search/empty search, color change event, delete cancel/confirm, export, sync | PASS for tested persistence after reload, downloaded class names, sync success response, aborted rename leaves original name | PASS at 1440x900, 768x1024, 390x844 in both themes; all row actions/counts in horizontal bounds, rename and delete-cancel actually clicked in all six | 15/15 browser groups PASS |
| Classes → Annotate → Classes | PASS active sections and header restoration | Hash navigation checked | No new backend behavior | Desktop navigation assertion | PASS (included above) |

Verification: `python scripts/browser_audit.py classes` against disposable Flask/SQLite
fixtures on port5055, real installed Chrome. Live workspace/project `m` untouched.
15/15 groups passed, no unexpected pageerror or network/console failures; the sole
failed request and console error were the deliberately aborted rename error test.
`python scripts/check_design_tokens.py`: zero violations.
`python -m unittest discover -s tests -p test_design_system.py`: 5/5 PASS.
Full-tree `git diff --check` reports an unrelated existing blank line at
`static/css/layout.css:394`; it was not changed in this task.

Files changed in this continuation: `static/css/classes.css`, `static/js/main.js`
(mobile metadata labels), `templates/pages/annotate.html` (help),
`scripts/browser_audit.py`, `scripts/summarize_browser_audit.py` (actual aggregation
date), this memory, `docs/annotate-control-checklist.md`, `DESIGN_SYSTEM.md`,
`docs/audit-browser-results.json`, retained Classes screenshots.
Evidence: `.audit-browser/classes-results.json` and the `classes` phase in
`docs/audit-browser-results.json`; `docs/audit-screenshots/classes-page-{light,dark}-{desktop,tablet,mobile}.png`.

Limits/next steps: native OS color-picker interaction, screen-reader behavior of mobile
rows, custom/compact themes, multiuser conflict/permissions, nonzero annotation-count
accuracy, and destructive label cleanup across legacy datasets are not certified here.
Sync tested its successful response, not an independent readback of generated YAML.
No merge-classes feature was added. The full-app audit remains incomplete (formal
19/80 gates unchanged); previous annotation/mobile and other pending tasks remain
tracked above. Read this section before changing Classes again; preserve direct
renaming and all mobile metadata rather than hiding columns.

## Design-system completion round, Add-to-Dataset card, Classes layout (13–14 November 2026)

User asked for an honest status of the UI standardization and to continue implementing what was incomplete; then to unify the "Add to Dataset" card on Upload and Annotate; then to make the Classes page use the full width. Status per requirement with evidence: `DESIGN_SYSTEM.md` §10. Summary: fonts/sizes/colours/radius/spacing/shadows/motion are centrally configurable and measured; button and list/card consistency are **partial**.

**Implemented**
- Global knobs `--radius-scale`, `--space-scale`, `--shadow-strength`, `--motion-scale`, `--shadow-rgb`. `scripts/tokenize_geometry.py` rewrote 536 radii, 2,159 spacing values, 49 shadows and 403 durations to knob-multiplied steps. Snapshot diff before vs after: 84/84 pixel-identical. The guard now also rejects raw radius/spacing/duration values; its self-test caught a broken regex during this work.
- Button role registry `scripts/apply_button_roles.py`: 30 families → 5 roles (action, action-sm, icon, icon-sm, chip). The approved class picker, drawing toolbar, nav rail and auth brand controls are excluded on purpose.
- Both modal systems (shared `.modal-header…` and the annotator's 10 `.modal-head…` dialogs) read `--modal-*` tokens; menus read `--menu-*`; themed tooltip for every `title` (`core/ui.js`); native checkbox/radio/range follow the accent.
- **Add to Dataset:** three implementations (Upload `usp-*`, Annotate `atd-*`, unused `sdm-*`) replaced by one `.ui-split-card` with `--split-card-*` tokens. Shared `rebalanceSplit()`: the Annotate card used to let ratios go wrong and disable Create.
- **Classes:** the page was capped at a 960px centred column. It is now full width (`--content-wide`) with an insights panel (Overview KPIs, Class balance, Needs attention).

**Bugs found and fixed (with evidence)**
- `/stats` `class_counts` lacked `id`, so the Classes page showed **0 annotations / 0 images for every class** in every project. Fixed in `app/api/media.py`; unit test `test_stats_class_counts_carry_class_id` fails without the fix and passes with it. Added `labelled_images` (images with ≥1 box): `annotated_images` counts images marked Done and was wrongly read as "annotated".
- Classes rename ignored HTTP 409, so a duplicate rename looked saved while the server refused it. Add used a client-guessed id instead of the server's `new_id`. Names were inserted unescaped into HTML.
- Mobile Annotate canvas collapsed to 26px: the unfinished media-library rule reserved the right-panel column even when collapsed. Fixed; `probe` 45/45.
- Autosave switch showed "on" in both states (annotate-v2 forced the accent fill).
- Shared `.ui-table-wrap` let absolutely positioned header labels widen the page (Classes mobile overflow).
- 846 dead selectors removed (old 2FA/sessions/settings tabs/legacy upload/three card versions) plus 9 exact duplicate rules; settings' dead `.switch` CSS removed.
- Test-harness bugs fixed and recorded as such, not app defects: a `page.evaluate` that awaited an open dialog (hang); a strict-mode locator; mid-transition measurement in `ds-geometry`.

**Testing (disposable fixture, real Chrome; live project `m` not touched)**
Final full run on the finished code: classes 16, project 21, ds-split-card 6, ds-controls 20, probe 45, nav-theme 37, ds-propagation 28, ds-geometry 28, ds-inventory 28, ds-snapshots 84, auth 19, dashboard 9, settings 18, members 3, media 2: **364 PASS, 0 FAIL**. `ai` 4/4 in an earlier run (no AI code changed since). Unit tests 47 run, 46 PASS, 1 symlink SKIP. Guard 0. All four converters idempotent. Evidence: `docs/audit-browser-results.json` (386 PASS, 39 OBSERVED aggregated), `.audit-browser/split-card-*.png`, `.audit-browser/classes-page-*.png`.

**Not done / honest limits**
- Button shapes per page remain varied (Annotate 21, other project sections 8–11), mostly specialised tool/nav/chip buttons; most annotator buttons don't use `.btn` markup.
- Dataset/Versions/Upload lists still use page-specific markup (on tokens); `.ui-tabs` not adopted; `main.js` still uses native `confirm()`.
- 262 selectors are overridden across main.css/annotate-v2.css (structural override layer).
- Custom/compact modes, Safari/Firefox and physical touch are not tested.
- The user's running server on :5000 needs its normal debug auto-reload (or a restart) to serve the `media.py` stats fix; browsers pick up CSS/JS via `asset()` versions on reload.

**Next tasks:** (1) adopt `.btn`/`.ui-table` markup in Dataset, Versions and Upload lists; (2) `main.js` confirms → `UI.confirm` with test updates; (3) snapshot custom/compact modes; (4) continue `docs/annotate-control-checklist.md`. Formal acceptance remains 19/80 gates.

## Classes rename popup (14 November 2026)

User asked for renaming in a popup showing the previous name, a new-name field and the image count, and asked whether renaming changes the class index. Answer recorded: **no**. Label files store only the class ID, and rename changes only the name in `project.json`. Changing a class's ID is not supported by the app today. It would mean rewriting every label `.txt`, suggestion sidecar and prompt-example file in the project (versions are immutable snapshots with their own `data.yaml`). It is **not built**, pending the user's decision.

Implemented: `#clsRenameModal` in `templates/pages/annotate.html` (annotator modal structure, `--modal-*` tokens). It shows the current name, colour, ID badge, annotation and image counts, the new-name field with an old → new preview, and a note that the ID is kept. `main.js` `_clsOpenRename/_clsBindRename/_clsCloseRename` replace the inline editor. Saving reuses the server-checked `_clsPageRename`. The modal is added to the global Escape list and closed by `showPage` when leaving Classes (including Classes → Annotate, which the generic close does not cover). The inline editor CSS was removed. Styles are in `static/css/classes.css` (`.cls-rn-*`, tokens only).

Tests (disposable fixture, real Chrome): `classes` 18/18, including:
- the popup shows the old name, `ID 0` and counts 3/1 from seeded annotations;
- save is disabled until the name changes;
- rename persists after reload and the ID and annotation count are unchanged;
- Escape, Cancel, × and backdrop all leave the name unchanged;
- a duplicate name shows an error and the popup stays open; empty names can't be saved;
- an aborted network request keeps the original name;
- popup bounds and screenshots in light/dark at three sizes (`.audit-browser/classes-rename-popup-*.png`).

Regression: `project` 21, `probe` 45, `nav-theme` 37, `ds-controls` 20, `ds-split-card` 6, all PASS. Unit tests 47 run, 46 PASS, 1 symlink SKIP. Guard 0. Live project `m` untouched.

## Change class ID (14 November 2026)

User request: change class indices, e.g. jcb 0, road 1, tree 2, 1_staff 3 → move tree to 0. Built as **Change ID** on the Classes page (`#` row button → `#clsReindexModal`). If the target ID is taken there are two modes: **Swap** (tree 0, jcb 2; only those two classes' lines change) or **Move and shift** (tree 0, jcb 1, road 2). A dry run previews the classes and line counts; Apply rewrites server-side.

Backend: `app/core/class_reindex.py` (plan/apply) and `POST /classes/reindex {mapping, dry_run}` in `app/api/classes.py`. Writes:
- the first token of every label line, with coordinates, polygons, spacing and CRLF byte-identical;
- `.suggestions.json` `class_id`;
- `prompt_examples.json` `class_id`;
- `project.json`;
- `data.yaml` (if present).

Never touched: `Versions/` (immutable snapshots) and internal `_`/`.` folders. Safety:
- validated one-to-one mapping (no merges);
- refuses an ID still used by leftover labels of a deleted class (delete scrubs only Active Work);
- 409 while another user holds a live annotation lock (own lock allowed);
- backup zip of every original plus `MAPPING.json` in `paths.class_id_backups_dir()` before writing;
- atomic tmp+replace writes with full in-memory rollback; no temp files left on failure;
- audit log `classes.reindex`; the AI example cache is cleared.

Frontend: flushes the pending autosave first, then remaps this tab's `state.bboxes`/`promptBoxes`/`selectedCls` and clears undo/redo. Old-ID snapshots there would otherwise write old numbers back.

Tests:
- `tests/test_class_reindex.py` 7/7: the user's scenario with swap and shift, dry run writes nothing, invalid mappings, orphan IDs, viewer 403, other-user lock 409 vs own lock, CRLF preserved, Versions untouched, backup contents, rollback with a failing write.
- Found and fixed during testing: a failed write left a `.reindex.tmp` file.
- New guard `test_every_used_custom_property_is_defined`.
- Browser `classes` 19/19, including `classes-change-id-swap-shift-rewrites-labels`: swap → label file `[0,1,1,1]` read back via API → shift back → `[0,0,0,1]` → Escape changes nothing.
- Regression: project 21, probe 45, nav-theme 37, ds-controls 20.
- Unit suite 55 run, 54 PASS, 1 symlink SKIP. Guard 0. Live project `m` NOT touched.

Limits: the same user's *other* open tabs cannot be detected; the popup warns. Versions created before a change keep old numbering; new versions should be created for training. Undo is via the backup zip (manual), not a UI button.

## Classes page UX pass (14 November 2026)

User asked to make Classes more user-friendly, modern and professional after the Change ID work. Changes (`templates/pages/annotate.html`, `static/js/main.js`, `static/css/classes.css`; tokens and shared components only):
- Cryptic `#`/trash icons replaced by a labelled ⋮ menu (shared `KebabMenu`): Rename…, Change colour…, Change ID…, Delete class.
- Sortable column headers with `aria-sort` and sticky table header; filter chips All / In use / Unused with counts; share % per class; `/` focuses search.
- Loading skeleton instead of fake zeros while `/stats` loads; "Couldn't load annotation counts" + Retry on failure.
- New-class default colour = the palette colour most distinct from existing classes. Before this, every new class defaulted to the same red, and a race against the class-list load also produced red.
- Insights are interactive: balance rows jump to and flash their class; the unused alert has "Show unused".

Bugs found in review and fixed, each now guarded by an assertion: balance rows collapsed into a 10px column (an older `.cls-dist li` grid rule won the cascade); the default colour was computed before classes loaded; near-identical greens (exact-RGB check only, now a colour-distance check ≥ 90).

Tests: browser `classes` 20/20, including `classes-ux-sort-filter-menu-colour-insights-loading`:
- sort both ways with `aria-sort`;
- chip counts and filtering, including the "Every class is in use" empty state;
- the four menu labels;
- distinct default colours (server-reloaded);
- "Show unused" and jump-to-row flash; `/` shortcut;
- held `/stats` shows skeletons and no zeros; failed `/stats` shows Retry, which recovers.

Regression: project 21, probe 45, nav-theme 37, ds-controls 20. Unit 55 run, 54 PASS, 1 skip. Guard 0. 7 dead selectors removed. Live project `m` untouched.

## Versions page UI/UX (14 November 2026)

User asked to improve the Versions page (`#versions`). Rebuilt list + detail on tokens/shared components: new `static/css/versions.css`; markup in `templates/pages/annotate.html`; `main.js` `_renderVersionsList/_renderVersionDetail/_closeVersionDetail/_verMenu/_verNum/_verCopyPath/_deleteVersion`.

Problems found and fixed:
- Phone layout rendered the detail behind the list (overlap). Now list↔detail with a back button at ≤1023px.
- `app._closeVersionDetail` was called by the old Close button but never defined (click threw).
- Version numbers were list positions, so deleting v1 relabelled v2 as v1. Now taken from the name, with position as fallback.
- Hardcoded `#60a5fa/#c084fc/#f59e0b` in JS gave the split different colours in list and detail. Now the shared `--split-*` tokens.
- Misleading UI: the "Augments" KPI and an unlabelled Preprocess/Augment wizard (settings are README-only). Now "Recorded only, not applied yet" warnings in wizard steps 3–4 and a "README only" note on the detail.
- Full machine path dominated the card. Now the project-relative path with Copy; tiny folders show "< 0.1 MB" instead of "0 MB".
- Native `confirm()` delete that ignored the server response. Now `UI.confirm` and a checked response.
- Annotate-only header controls shown on Versions. The compact header is now ONE shared rule for Dataset/Classes/Versions (removed the per-page copies).
- Dim `--tx3` body text in the wizard (≈1.7:1 in dark). Readable text moved to `--tx2`.
- 73 dead `vs-*` selectors removed.

Not a bug: the probe showed 1 image per version because each upload call is its own batch and only one batch had been added to the dataset.

Tests: new browser phase `versions` 10/10 on seeded data:
- list order, Latest badge, token split colours;
- keyboard selection;
- detail KPIs equal the API; note, relative path, recorded-only note, folder size;
- Copy path read back from the clipboard;
- ⋮ menu items; ZIP download;
- delete cancel keeps / confirm removes (API), stable `v2` after deleting v1;
- wizard steps 3–4 warnings;
- compact header, desktop/tablet/mobile × light/dark, list↔detail with no horizontal overflow;
- empty state and create CTA.

Project phase updated to delete through the ⋮ menu + themed confirm: 21/21. Regression: classes 20, probe 45, nav-theme 37, ds-controls 20, ds-split-card 6; unit 55 run, 54 PASS, 1 skip; guard 0. Live project `m` untouched.

Still NOT implemented: actual resize/auto-orient/augmentation of version images (requires label transforms for letterbox/flip/rotate). Now clearly labelled instead of implied.


## Readable text in every theme + Version wizard polish (14 November 2026)

User request: fix dark-theme text that doesn't show on the Create Dataset Version
wizard, make it global (Theme Settings custom themes included), never page by page.

Done (central, not per page):
- Contrast tokens: dark `--tx2 #a0a0c5`, `--tx3 #8989a8`; light `--tx3 #5f6b63`,
  `--warning` text `#845300`. New `--accent-text` (accent as TEXT; fills keep
  `--accent`) and `--split-train/val/test-text`. 188 `color: var(--accent)` text
  rules moved to `--accent-text`; 42 split rules routed through `--split-*`.
- `theme.js`: custom theme / custom accent recompute `--tx2`, `--tx3`,
  `--accent-text` until WCAG AA on every surface; custom mode sets `light-mode`
  on `<html>` only (on body it shadowed the custom palette — bug fixed).
- `main.js`: hardcoded hex colours in JS-built markup (upload batch source and
  status badges, YOLO-import split rows, match badges, class chips) → tokens +
  `color-mix`. Remaining hex in main.js = canvas painting + `CLASS_PALETTE`
  (deliberately unthemed).
- Wizard: footer buttons joined the `action` button role (`apply_button_roles.py`),
  counts pluralised (`_plural`: "1 image"), removed a dead mis-argued `set()` call
  that flashed "vwTrainCount%" in the Train % label.
- New browser phase `ds-contrast`: every visible text, 14 pages + 5 wizard steps,
  light / dark / custom-dark / custom-light.

Verified: contrast failures 723 → 0 (`ds-contrast` 56/56); `versions` 10/10;
token guard 0 violations; unit tests 55 run, 54 pass, 1 Windows-symlink skip.
Full regression afterwards: classes 20/20, project 21/21, ds-controls 20/20,
ds-split-card 6/6, nav-theme 37/37, probe 93/93, ds-propagation 28/28.

Known gap: `check_design_tokens.py` does not scan colour literals inside JS
template strings; that is how the main.js colours slipped through. Next task:
extend the guard to JS `style="..."` strings.

### Create Dataset Version wizard → centred dialog (14 November 2026)

User: the wizard opened as a side panel; wanted it centred, cleaner, Roboflow-like.
- New shared component `.ui-wizard` in `components.css` + `--wizard-*` tokens:
  centred 960×680 card, step rail on the left (label + hint, ✓ done, click to go
  back), content scrolls, footer pinned; tablet = step strip; phone = full screen.
- Old drawer shell CSS (24 rules) removed from `main.css`; duplicate number
  bubbles removed from the step titles; Continue is now a solid primary button.
- Bugs found by the new test and fixed: Esc did not close the wizard; the
  close animation referenced an undefined `vwSlideOut` keyframe (no animation).
  Focus now goes to the version name on open and back to the button on close.
- Verified: new phase `wizard` 12/12 (centred + inside viewport, 4 themes ×
  desktop/tablet/phone, navigation/Esc/close, screenshots reviewed);
  `versions` 10/10, `ds-contrast` 56/56, `ds-controls` 20/20; unit tests OK
  (1 Windows skip); token guard 0.

## Compact mode annotation sidebar clipping — 14 November 2026

User reported the top text in RIGHT SIDEBAR being cut after Settings → Layout
Preferences → Compact. Reproduced through the real Settings control, then opening
`/pages/annotate?workspace_id=1&project=audit-project#annotate` in Chrome.

Cause: `modes.css` overrode `--tb-h` to 38px, even though the annotation header
renders at 52px desktop, 148px tablet, 184px mobile. The workspace/right tabs
therefore began behind the header (14/110/146px overlap). All six compact-mode
light/dark viewport checks failed before the fix; all six expanded checks passed.

Fix: removed duplicate shell height/status-bar tokens from `modes.css`; metrics
remain owned by `tokens.css`. Changed the compact `--tb-h` desktop fallback from
38 to 52px, matching the actual annotation header while preserving its responsive
height and the other compact spacing preferences. No local text offsets, smaller
fonts, or sidebar-only patches. Both sidebars/workspace now start below the header.

Retest: `python scripts/browser_audit.py compact-sidebar`: **12/12 PASS**. Matrix:
compact/expanded × light/dark ×1440x900,768x1024,390x844. Each check asserts tabs
below the header and no tab-content overflow, clicks Labels/Properties/Raw/Notes,
and collapses/restores the right sidebar. Settings selection is made with the real
Compact card before navigation. Reviewed desktop light and mobile dark screenshots.
No console/pageerror/network failures in this run. Disposable fixture only; live
project `m` untouched. Token guard:0 violations. Design-system unit tests:6/6 PASS.
These tests cover the reported shell overlap and sidebar tabs, not all annotation
editing or physical-device touch behavior.

Files: `static/css/modes.css`, `static/css/tokens.css`, `scripts/browser_audit.py`,
this memory, `docs/annotate-control-checklist.md`, evidence JSON/screenshots.
Evidence: `compact-sidebar` in `docs/audit-browser-results.json` and
`docs/audit-screenshots/sidebar-compact-{light,dark}-{1440,768,390}.png`.
Future rule: never give Compact mode a workspace top offset independent of the
rendered responsive header height. Full application audit remains incomplete;
continue the pending feature/permission checks rather than repeating this fix.

## Upload header shows annotation state — 14 November 2026

User: current image/annotation information appears in the shared top header on
`#upload`; this information belongs only on `#annotate`.
Cause: all six sections share one header. The compact header rule applied only
to Dataset/Classes/Versions; Upload and Projects retained image/save controls,
and annotation progress in `.ah-left` was not scoped at all.

Fix: `static/css/annotate-v2.css` now applies the shared project header to every
active non-Annotate section. Brand, project selector and account remain available.
Image name/status/navigation, annotation progress and its separator, save/Auto/Done
and editor toolbar actions are hidden there and restored when Annotate activates.
`templates/pages/annotate.html` comment identifies the progress as editor-only.
This uses the existing shared theme and responsive header-height tokens.

Verified in real Chrome against disposable local data: `header-scope` 12/12 PASS
(light/dark × expanded/compact ×1440/768/390 widths). Each group visits Upload,
Dataset, Versions, Classes, Projects, then Annotate; checks editor state visibility,
project selector/account availability, compact Upload header height, and restored
editor controls on return. Direct Upload navigation and reload also checked.
Reviewed mobile Upload screenshot. No live project data changed.
Token guard:0 violations; design-system unit tests:6/6 PASS.
Initial test incorrectly expected the intentionally hidden native checkbox to be
visible; corrected to inspect its visible `.autosave-toggle` label before final run.
This is header/navigation verification, not a new audit of all upload controls.

Files: annotate-v2.css, annotate.html, scripts/browser_audit.py, this memory,
docs/annotate-control-checklist.md, audit-browser-results.json and screenshots.
Evidence: `header-scope` phase; retained `upload-header-expanded-{light,dark}-390.png`.
Future rule: current-image UI belongs only to Annotate, not other project sections.
The full-app audit remains incomplete; continue pending workflow/permissions tests.

### Dark styles in Theme Settings (14 November 2026)

User shared three dark references (deep indigo + blue glow; blue navy; neutral
black + vivid blue) and asked for more dark themes in Theme Settings.
- Settings → Theme → Dark Mode → **Dark style**: Classic (default, unchanged),
  Midnight Blue, Navy, Carbon. One token block per style in `tokens.css`;
  `theme.js` applies `<html data-dark-style>` from `am_dark_style` before
  first paint; Light/Custom ignore it; Reset restores Classic.
- Choosing a style drops an earlier accent pick; a later accent still wins and
  `--accent-text` is now computed against the real (style) surfaces.
- Global fixes found on the way: `--accent-a04…a40` derive from `--accent`
  (stayed teal after a custom accent); text on purple fills uses `--on-purple`
  (4 rules; 3.1:1 with white on-fill).
- Verified: new phase `dark-styles` 8/8 (all 14 pages per style, before first
  paint; screenshots reviewed); `ds-contrast` 98/98 (7 themes); `wizard` 21/21;
  settings, nav-theme 37/37, ds-propagation 28/28, ds-controls 20/20,
  versions 10/10, probe 63 pass + 30 observed; unit tests OK (1 Windows skip);
  token guard 0.
