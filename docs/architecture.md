# Architecture

[← Documentation home](README.md)

- [At a glance](#at-a-glance)
- [System overview](#system-overview)
- [Layers](#layers)
- [How a request flows](#how-a-request-flows)
- [Data model](#data-model)
- [Folder structure](#folder-structure)
- [Data layout on disk](#data-layout-on-disk)
- [Maintenance](#maintenance)

Contributor notes, design decisions and known pitfalls are kept in [`CLAUDE.md`](../CLAUDE.md) at the repository root.

---

## At a glance

| | |
|---|---|
| **Type** | Self-hosted web application, single server |
| **Backend** | Python · Flask · SQLAlchemy |
| **Frontend** | Server-rendered pages + vanilla JavaScript, **no build step** |
| **AI** | PyTorch · Ultralytics (YOLO, SAM3) · DINOv2 via timm, on GPU or CPU |
| **Storage** | SQLite for accounts and teamwork; the **filesystem** for images and labels |
| **Labels** | Standard YOLO `.txt` files, readable by any YOLO tool |

## System overview

```mermaid
flowchart LR
    U(["👤 Users<br/><sub>annotators · reviewers · owners</sub>"])

    subgraph CLIENT["🌐 Browser — no build step"]
        direction LR
        P1["Sign in · Dashboard<br/>Members · Settings"]
        P2["Annotate app<br/><sub>upload · annotate · dataset · versions</sub>"]
        P3["Canvas engine<br/><sub>main.js</sub>"]
        P4["AI panels<br/><sub>Smart Detect · AI Annotate</sub>"]
    end

    subgraph SERVER["🐍 Flask server"]
        direction TB
        AUTH["🔐 JWT auth + role check<br/><sub>owner · editor · viewer</sub>"]
        API["app/api — HTTP routes<br/><sub>auth · workspaces · projects<br/>uploads · media · annotations<br/>classes · datasets · versions<br/>locks · audit · AI</sub>"]
        CORE["app/core — business logic<br/><sub>paths · YOLO I/O · suggestions<br/>media index · datasets · versions<br/>AI models · GPU/CPU devices</sub>"]
        AUTH --> API --> CORE
    end

    subgraph AI["🧠 AI models — GPU ⇄ CPU"]
        direction TB
        M1["Your YOLO .pt<br/><sub>Smart Detect</sub>"]
        M2["SAM3<br/><sub>finds objects</sub>"]
        M3["DINOv2<br/><sub>decides the class</sub>"]
    end

    subgraph DATA["💾 Storage"]
        direction TB
        D1[("SQLite<br/><sub>users · workspaces<br/>images · locks · audit</sub>")]
        D2[("Media index<br/><sub>.media_index.db per project</sub>")]
        D3[("📁 workspace/<br/><sub>images · YOLO labels<br/>datasets · versions</sub>")]
    end

    subgraph EXT["🔌 External tools"]
        direction TB
        E1["ffmpeg<br/><sub>video → frames</sub>"]
        E2["Hugging Face<br/><sub>model downloads</sub>"]
        E3["SMTP<br/><sub>reset emails</sub>"]
    end

    U --> CLIENT
    CLIENT -- "JSON over HTTP<br/>JWT" --> SERVER
    SERVER --> AI
    SERVER --> DATA
    SERVER -.-> EXT

    classDef client fill:#e0f2fe,stroke:#0284c7,color:#0c4a6e
    classDef server fill:#ede9fe,stroke:#7c3aed,color:#3b0764
    classDef ai fill:#fce7f3,stroke:#db2777,color:#831843
    classDef data fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef ext fill:#f1f5f9,stroke:#64748b,color:#1e293b
    classDef user fill:#fef3c7,stroke:#d97706,color:#78350f
    class P1,P2,P3,P4 client
    class AUTH,API,CORE server
    class M1,M2,M3 ai
    class D1,D2,D3 data
    class E1,E2,E3 ext
    class U user
    style CLIENT fill:#f0f9ff,stroke:#7dd3fc
    style SERVER fill:#f5f3ff,stroke:#c4b5fd
    style AI fill:#fdf2f8,stroke:#f9a8d4
    style DATA fill:#f0fdf4,stroke:#86efac
    style EXT fill:#f8fafc,stroke:#cbd5e1
```

## Layers

| Layer | Responsibility | Where |
|---|---|---|
| **Pages** | Sign-in, dashboard, members and settings are standalone pages; the annotate app is one page with hash routes (`#upload`, `#annotate`, `#dataset`, `#versions`, `#classes`) | `templates/` |
| **Canvas engine** | Drawing, editing, undo/redo, auto-save, and the suggestion lifecycle (`Boxes` module) | `static/js/main.js` |
| **AI front-ends** | Smart Detect bar; AI Annotate panel for text and box prompts | `templates/pages/annotate.html`, `static/js/features/prompt-annotate.js` |
| **Auth** | JWT from the `Authorization` header or a cookie; each workspace route checks the member's role | `app/utils/security.py` |
| **API** | Thin routes: parse the request, call core, return JSON | `app/api/` |
| **Core** | All business rules. `paths.py` is the only place that builds file paths | `app/core/` |
| **AI engine** | Model loading and caching, prompt handling, and device choice: GPU with half precision, falling back to CPU | `ai_models.py`, `prompt_models.py`, `devices.py` |
| **Storage** | SQLite (hardened: WAL, foreign keys, busy timeout) plus the project folders on disk | `app/models/`, `workspace/` |

**Two sources of truth, by design.** The database holds accounts, membership, locks, audit history and batch metadata. **Images and labels live only on disk**, in standard YOLO layout, so a project folder is always usable without the application.

## How a request flows

### Saving an annotation

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Canvas as Canvas (main.js)
    participant API as POST /annotations
    participant Core as core: yolo · suggestions
    participant Disk as labels/
    participant DB as SQLite + media index

    User->>Canvas: Draw a box, pick its class
    Canvas->>Canvas: Auto-save after a short pause
    Canvas->>API: Boxes for this image (JWT)
    API->>API: Check role + image lock
    API->>Core: Split by state
    Core->>Disk: <name>.txt ← confirmed boxes only
    Core->>Disk: <name>.suggestions.json ← pending review
    Core->>DB: Mark image annotated, write audit entry
    API-->>Canvas: success
```

### Box-prompt prediction (AI Annotate)

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Panel as AI Annotate panel
    participant API as POST /ai/prompt
    participant Dev as devices
    participant SAM3
    participant DINO as DINOv2

    User->>Panel: Open the next image
    Panel->>API: mode = "examples"
    API->>Dev: Run on the best device
    Dev->>SAM3: GPU (fp16) → GPU (fp32) → CPU
    SAM3->>SAM3: Encode examples on their own images (cached)
    SAM3-->>DINO: Candidate boxes on this image
    DINO-->>API: Class of the nearest example per box
    API-->>Panel: Suggestions + confidence
    Panel-->>User: Dashed boxes · Enter accepts · Delete rejects
```

## Data model

```mermaid
erDiagram
    USERS ||--o{ WORKSPACE_MEMBERS : "belongs to"
    WORKSPACES ||--o{ WORKSPACE_MEMBERS : "has"
    WORKSPACES ||--o{ UPLOAD_BATCHES : "by id"
    WORKSPACES ||--o{ IMAGES : "by id"
    UPLOAD_BATCHES ||--o{ IMAGES : "contains"
    UPLOAD_BATCHES ||--o{ ASSIGNMENTS : "assigned via"
    WORKSPACES ||--o{ ANNOTATION_LOCKS : "by id"
    USERS ||--o{ AUDIT_LOG : "acts in"

    USERS {
        int id
        string public_id "USR-XXXXXX"
        string email
    }
    WORKSPACES {
        int id
        string public_id "WS-XXXXXX = folder name"
    }
    WORKSPACE_MEMBERS {
        int user_id FK
        int workspace_id FK
        string role "owner · editor · viewer"
    }
    IMAGES {
        int workspace_id
        string project
        string rel_path
        bool is_annotated
        bool is_null
    }
```

Only `workspace_members` uses database-enforced foreign keys; the other tables refer to a workspace **by id**. Each project also keeps a small SQLite **media index** (`.media_index.db`) for fast listing, filtering and duplicate detection.

## Folder structure

```
annomaster/
├── run.py                  Entry point
├── config.py               Settings (reads .env)
├── migrate_db.py           Adds new columns/tables to an existing database
├── app/
│   ├── api/                HTTP routes — auth, workspaces, projects, uploads, media,
│   │                       annotations, classes, datasets, versions, locks, audit, AI
│   ├── core/               Business logic — paths, YOLO I/O, media index, datasets,
│   │                       versions, tags, suggestions, password reset, AI models,
│   │                       SAM3 prompting, box-prompt examples, GPU/CPU devices
│   ├── models/             SQLAlchemy — users, workspaces, images, upload batches,
│   │                       annotation locks, assignments, audit log
│   └── utils/              JWT security, public IDs, errors, logging
├── static/
│   ├── css/                Design tokens → base → layout → page sheets → modes
│   └── js/                 main.js (annotation engine) + features/ (AI Annotate,
│                           projects, workspace, settings, auth)
├── templates/              auth/ (login, register, forgot password), workspace/
│                           (dashboard, members), pages/ (annotate app, settings)
├── models/                 YOLO / SAM3 weights
├── scripts/                Backup, consistency check, v1 → v2 migration
├── docs/                   This documentation
└── workspace/              Your images and labels (not committed)
```

## Data layout on disk

```
workspace/<WS-XXXXXX>/projects/<project>/
├── Active_Work/job_<DATETIME>/
│   ├── images/
│   └── labels/
│       ├── <name>.txt                ← confirmed boxes (YOLO format)
│       └── <name>.suggestions.json   ← AI suggestions awaiting review (never exported)
├── Completed_Datasets/job_<DATETIME>/
│   └── train/ valid/ test/  → images/ + labels/
├── Versions/<name>/                  ← immutable snapshot + data.yaml + README.md
├── project.json                      ← classes and per-project settings
├── prompt_examples.json              ← AI Annotate box-prompt examples (while the panel is open)
└── .media_index.db                   ← fast media index
```

A label file's location always follows from its image: `images/` becomes `labels/`. Exports and versions copy labels by exact `<name>.txt`, so suggestion files can never leak into a dataset.

## Maintenance

```bash
python migrate_db.py                 # add new columns/tables to an existing database (safe to re-run)
python scripts/check_consistency.py  # report database ↔ filesystem drift
python scripts/backup.py             # snapshot the database and the workspace folder together
```
