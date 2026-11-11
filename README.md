# AnnoMaster v2

Multi-user, workspace-based YOLO annotation platform.
Refactored from a monolithic 4-file app to a clean modular architecture.

## Quick Start

```bash
cd annomaster
pip install -r requirements.txt
cp .env.example .env        # edit SECRET_KEY and JWT_SECRET
python run.py               # → http://localhost:5000
```

1. Open `http://localhost:5000` → redirected to `/login`
2. Click **Create one free** → register
3. Create a **Workspace** from the dashboard
4. Create a **Project** inside the workspace
5. Click the project → full annotation UI opens

## Architecture

```
annomaster/
├── run.py                    Entry point
├── config.py                 Settings (reads .env)
├── app/
│   ├── __init__.py           App factory + blueprints
│   ├── api/                  Thin route handlers
│   │   ├── auth.py           /api/auth/* + /login /register
│   │   ├── workspace.py      /api/workspaces/* + dashboard + members pages
│   │   ├── projects.py       /api/workspaces/<id>/projects/*
│   │   ├── media.py          image, thumbnail, stats
│   │   ├── annotations.py    YOLO read/write, null marking
│   │   ├── classes.py        class CRUD + sync
│   │   ├── uploads.py        upload/import/add_to_dataset
│   │   ├── datasets.py       completed datasets, export
│   │   └── versions.py       version snapshots + download
│   ├── core/                 Business logic (no Flask deps)
│   │   ├── paths.py          Workspace-aware path builder ← key file
│   │   ├── storage.py        JSON read/write helpers
│   │   ├── yolo.py           YOLO parse/write (original logic)
│   │   ├── media.py          image discovery, thumbnails
│   │   ├── projects.py       project lifecycle
│   │   ├── datasets.py       dataset build/list
│   │   └── versions.py       version snapshot builder
│   ├── models/
│   │   ├── user.py           User (email, bcrypt password)
│   │   └── workspace.py      Workspace + WorkspaceMember
│   └── utils/
│       ├── security.py       JWT, @login_required, @workspace_role_required
│       ├── errors.py         HTTP helpers
│       └── logger.py         Logger factory
├── static/
│   ├── css/
│   │   ├── main.css          Original annotator CSS (intact)
│   │   ├── auth.css          Login / Register pages
│   │   ├── layout.css        Navbar, dashboard, members
│   │   ├── workspace.css     Workspace-specific overrides
│   │   ├── upload.css        Upload page
│   │   ├── dataset.css       Dataset page
│   │   ├── versions.css      Versions page
│   │   └── classes.css       Classes page
│   └── js/
│       ├── core/api.js       Fetch wrapper (injects JWT, builds URLs)
│       ├── core/state.js     Lightweight global state
│       ├── core/utils.js     Shared helpers (escapeHtml, badges, modals)
│       ├── engine/canvas.js  Original drawing engine (reference copy)
│       ├── features/auth.js  Login / logout / requireAuth
│       ├── features/workspace.js  Workspace list + MembersFeature
│       ├── features/projects.js   Project grid
│       └── main.js           Patched original script.js (workspace URLs + JWT)
└── templates/
    ├── layout/navbar.html    Shared top nav
    ├── auth/login.html       Sign-in page
    ├── auth/register.html    Registration page
    ├── workspace/dashboard.html  Workspace + project dashboard
    ├── workspace/members.html    Invite / role management
    └── pages/annotate.html   Full annotation SPA (original UI)
```

## Roles

| Action            | owner | editor | viewer |
|-------------------|:-----:|:------:|:------:|
| Annotate          | ✅    | ✅     | 👁     |
| Upload / Import   | ✅    | ✅     | ✗      |
| Manage classes    | ✅    | ✅     | ✗      |
| Invite members    | ✅    | ✗      | ✗      |
| Change roles      | ✅    | ✗      | ✗      |
| Delete workspace  | ✅    | ✗      | ✗      |

## Migrate from v1

```bash
python scripts/migrate_v1_to_v2.py \
  --owner-email you@example.com \
  --workspace-name "My Workspace"
```

## File Storage

```
workspace/
  <folder_name>/          ← stored in DB (Workspace.folder_name)
    projects/
      <project_name>/
        Active_Work/
          job_2024-01-01_12-00-00_000/
            images/   labels/
        Completed_Datasets/
          job_.../
            train/images/  train/labels/
            valid/images/  valid/labels/
            test/images/   test/labels/
        Versions/
          <version_name>/
            images/train|val|test/
            labels/train|valid|test/
            data.yaml
        project.json
        versions.json
```
