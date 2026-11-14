# Code review and test report — 13 November 2026

This is the original four-defect report. See [PROJECT_AUDIT_AND_PROGRESS.md](../PROJECT_AUDIT_AND_PROGRESS.md)
for the broader audit, newer fixes and current test totals.

## Scope and result

Reviewed the live root Flask application using `CLAUDE.md`. This is a targeted review of authentication, workspace permissions, media paths, annotation persistence and locking, not a complete security audit. The in-progress `annomaster-next/` port was excluded as instructed by `CLAUDE.md`.

Added `tests/test_review.py`, using Python's standard-library unittest runner, an in-memory application database and a temporary workspace. Existing production database, images, labels and models were not used for writes. The initial review left application behavior unchanged; the follow-up fixes below are now implemented.

Initial result: **10 tests: 6 passed and 4 expected failures**. Follow-up result: **16 tests: 15 passed, 1 skipped, no expected failures**. All four reproduced issues are fixed and their regression checks pass. The symlink test is skipped because Windows does not grant symlink creation privileges. Python syntax parsing also passed for 50 files across `app/`, `scripts/`, `config.py` and `run.py`. SQLAlchemy emitted a legacy `Query.get()` warning.

## Implemented fixes

- Shared `resolve_project_path` rejects absolute, drive-relative, UNC, traversal and alternate-stream paths, and checks resolved containment. Project names are validated. Media, annotation reads/writes, null operations, locks, cover-from-path, AI image resolution and dataset image deletion use the shared containment checks. Derived label and suggestion-sidecar destinations are checked too.
- Null POST and DELETE now enforce the existing edit-lock conflict check before changing files or metadata. Backslash and forward-slash lock paths share a normalized representation.
- `validate_boxes` rejects invalid dimensions, nonfinite coordinates, invalid class IDs, malformed polygons and dimensions that round to zero at YOLO precision. HTTP saves validate the complete payload before changing existing labels; the core writer raises `ValueError` on invalid input. Empty valid lists still clear annotations.
- Auth endpoints validate JSON object shape and string field types before accessing them, returning JSON HTTP 400 for invalid input.

The fixes do not repair previously stored invalid labels or redesign concurrent locking. The tests use disposable data; no migrations or production-data edits were needed.

## Original findings, in priority order (now fixed)

### 1. High: media paths escape project and workspace boundaries

Location: `app/api/media.py`, `api_image` (line 104); related unchecked path construction in `api_thumbnail` and `app/api/annotations.py`.

The image route joins an untrusted `path` directly onto the project directory and then uses `send_file`. An absolute path replaces the project prefix; relative `..` components can also escape. Workspace membership authorizes the selected workspace but does not authorize arbitrary files readable by the server process.

Confirmed with a viewer token and an absolute path to a temporary sentinel outside the project: the route returned HTTP 200 instead of rejecting access. This can expose files from other workspaces or server configuration. Annotation endpoints similarly accept unchecked paths before deriving label destinations; arbitrary write impact needs additional endpoint-specific testing.

Recommended fix: add a shared resolver in `app/core/paths.py` that rejects absolute paths and ensures the resolved result remains inside the resolved project directory. Apply it consistently to image, thumbnail, annotations, null, AI and other user-controlled file paths. Validate project names too. Test sibling workspaces, traversal, absolute Windows/UNC paths and symlink escapes; never test against real secrets.

Regression: `test_regression_image_path_must_stay_in_project`.

### 2. High: marking an image null bypasses an active edit lock

Location: `app/api/annotations.py`, `api_null` (line 166).

Regular annotation POST calls `_check_lock_conflict`; the null endpoint does not. In the test, an owner saved a confirmed label and acquired the image lock, then a different editor posted `/null`. It returned 200 and replaced the confirmed label with an empty file. This destroys the saved annotation despite the advertised lock protection. The DELETE branch also lacks the lock guard, though that branch was not separately exercised.

Recommended fix: enforce the same conflict check before any null operation writes or deletes data, and test both POST and DELETE. Normalize paths before lock lookup so equivalent spellings cannot bypass locks.

Regression: `test_regression_null_must_respect_lock`.

### 3. Medium: label writer accepts boxes that the reader discards

Location: `app/core/yolo.py`, `write_yolo_label` (around lines 90–104), compared with `parse_yolo_label` and `is_valid_annotation_file`.

The writer accepts positive width/height greater than 1; the reader and validator require coordinates in 0..1. A box with width 2 is persisted, but omitted when reloaded and considered invalid by the validator. The annotation API can still report success, leading to disappearing labels and inconsistent status.

Recommended fix: share validation between writer, reader and HTTP input handling. Reject invalid input with HTTP 400 before overwriting existing labels. Include class IDs, finite values and polygon vertex counts in the shared contract. Validate a mixed valid/invalid payload without silently losing existing annotations.

Regression: `test_regression_writer_reader_agree_on_box_size`.

### 4. Medium: non-object JSON produces an unhandled login exception

Location: `app/api/auth.py`, `login` (lines 70–71); similar parsing patterns appear in other handlers.

Posting a nonempty JSON array reaches `data.get()` and raises `AttributeError`, producing HTTP 500 instead of a client validation error. The original regression reproduced the 500 response; it now asserts HTTP 400. Unexpected field types can cause related failures.

Recommended fix: validate that the body is an object and each field has the required type before calling `.get()`, `.strip()` or slicing. Return a consistent JSON 400 response. Extend tests to arrays, strings, numeric fields and malformed bodies across write routes.

Regression: `test_regression_invalid_json_shape_is_client_error`.

## Passing checks

| Check | Observed behavior |
|---|---|
| Health and pages | Health 200; login/register/reset pages 200; dashboard redirects anonymous access; authenticated dashboard and key templates render |
| Authentication and membership | Anonymous `/me` 401; authenticated `/me` 200; outsider annotations 403; viewer save 403 |
| Login | Incorrect password 401; correct password 200 |
| Annotation lifecycle | Confirmed label stored in `.txt`; suggestion stored separately and returned on read |
| Regular save lock | Different editor's save rejected with 409 |
| Reset token | Token accepted before password change and invalid afterward |

## Limits and follow-up

Node was unavailable on PATH, so JavaScript execution and syntax checks were not run. No browser interactions, GPU/AI inference, video extraction, upload/import, export/version end-to-end flows, email delivery, migration runs, concurrency stress tests or port-stack checks were performed. The image fixture is deliberately not a decoded image; these tests do not validate image processing. Rate limiting is disabled in test configuration and is not covered.

Static deployment observations: `config.py` permits the fallback secret `change-me-in-production`; `run.py` binds all interfaces with debug enabled. Use explicit production secrets and a production WSGI server. These observations are separate from the four reproduced defects.

All four original expected-failure decorators have been removed. Expanded checks cover malicious path variants, preservation of labels after invalid saves, null POST/DELETE conflicts, mixed path separators, valid polygon round trips, clearing labels and JSON shape/type errors. Keep running the suite after changes; passing these focused checks is not a complete security or browser audit.
