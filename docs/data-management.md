# Upload, Datasets & Versions

[← Documentation home](README.md)

- [Uploading images and video](#uploading-images-and-video)
- [Importing a YOLO dataset](#importing-a-yolo-dataset)
- [Datasets](#datasets)
- [Versions and download](#versions-and-download)
- [How data is stored](#how-data-is-stored)

---

## Uploading images and video

- Drag and drop **images** or a whole **folder**: JPG, PNG, BMP, TIFF, WebP.
- **Video → frames**: MP4, AVI, MOV, MKV, WMV, FLV, WebM, M4V, TS / M2TS / MTS, **DAV (CCTV / Dahua)** and raw H.264 / H.265 streams. Frames are extracted with **ffmpeg**; if ffmpeg is not installed, OpenCV is used as a fallback, which handles common formats but not every CCTV codec.

  | Option | Choices |
  |---|---|
  | Frames per second | 1 · 2 · 5 · 10 · 15 · 24 · 30 |
  | Resolution | original · 1080p · 720p · 480p · custom |
  | Output format | JPG · PNG |

- **Identical files are skipped** automatically (MD5 check).
- Each upload becomes a **batch (job)** that can be tagged and **assigned** to a teammate.

## Importing a YOLO dataset

- Import an existing **YOLO dataset ZIP**.
- Preview before importing: images, labels, classes and `data.yaml`.
- **train / valid / test** folders are detected, with a count of images that have matching labels.
- Classes are read from `data.yaml`.
- **Duplicate handling**: skip existing, rename new, or overwrite.
- Choose to import images, labels or both, and optionally split right after import.

## Datasets

- Move finished jobs into **Completed Datasets**.
- **Split** with train / valid / test sliders.
- Organise batches and datasets with **tags** and filters.
- **Dataset statistics**: images, objects and classes.

## Versions and download

A step-by-step wizard creates an **immutable snapshot** of the project's labelled images:

1. **Name** the version and add optional notes.
2. **Split** into train / valid / test with sliders or presets (default 70 / 20 / 10, shuffled).
3. **Review** the summary and create it.

Each version contains `images/` and `labels/` per split, a `data.yaml` and a `README.md` with statistics. **Download** any version as a ZIP, ready for `yolo train`.

- Only **annotated and Null images** are included; images nobody has labelled yet are left out.
- Only **human-confirmed** labels are included; see [Reviewing suggestions](ai-labelling.md#reviewing-suggestions).

> **Note:** the wizard also offers preprocessing (resize, auto-orient, normalize) and augmentation options. These are currently **recorded in the version's README only**; images are exported at their original size and unmodified.

## How data is stored

Annotations stay on disk in standard **YOLO format**; the database stores only users, workspaces, membership, locks and audit history. See [Architecture](architecture.md#data-layout-on-disk) for the folder layout.
