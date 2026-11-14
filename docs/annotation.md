# Manual Annotation

[← Documentation home](README.md)

The annotation canvas is a complete labelling studio, fast enough to label thousands of frames by hand. Every change is saved automatically as a standard YOLO `.txt` file.

- [Drawing tools](#drawing-tools)
- [Classes](#classes)
- [Editing and speed features](#editing-and-speed-features)
- [View controls](#view-controls)
- [Media library](#media-library)

All keyboard shortcuts are listed in **[Keyboard shortcuts](keyboard-shortcuts.md)**.

---

## Drawing tools

| Tool | Key | How it works |
|---|:---:|---|
| **Bounding box** | <kbd>B</kbd> | Drag anywhere to draw, **even inside another box**, so nested objects work |
| **Polygon** | <kbd>P</kbd> | Click points; <kbd>Enter</kbd> closes the shape |
| **Select / edit** | <kbd>V</kbd> | Move, resize with handles, change class, delete |
| **Pan** | <kbd>Space</kbd> | Hold and drag |

**Draw mode draws, select mode edits.** In box mode a drag always starts a new box; to change an existing box, switch to select mode.

## Classes

- A **class popup** opens after every box: search, use the arrow keys and <kbd>Enter</kbd>, or create a new class on the spot.
- **Repeat mode** (<kbd>R</kbd>) skips the popup and reuses the last class.
- Change a selected box's class with <kbd>C</kbd>.
- Rename classes, choose **class colours** and sync classes across the project.
- **Rename** (Classes page → click the name): only the name changes. Label files store the class
  *ID*, never the name, so existing annotations stay assigned.
- The Classes page list can be **sorted** (click a column header) and **filtered**
  (All / In use / Unused); every row's ⋮ menu has Rename, Change colour, Change ID and Delete.
  New classes get a colour that differs from the existing ones. Press <kbd>/</kbd> to search.
- **Change ID** (Classes page → ⋮ → *Change ID…*): give a class another number, e.g. move
  `tree` from 2 to 0. If another class already has that ID, choose **Swap** (tree 0, jcb 2) or
  **Move and shift the others** (tree 0, jcb 1, road 2). The popup previews exactly which classes
  and how many label lines change. Every label `.txt`, AI-suggestion file and AI example is
  rewritten; a backup zip of the originals is saved first in `<project>/_backups/class_ids/`
  (unzip it over the project folder to undo). Already-created **Versions keep their old
  numbering**: create a new version afterwards for training. The change is refused while
  another user has an image open in the project; close the project in your other tabs too.
- The side panel shows live **per-class object counts**.

## Editing and speed features

- **Auto-save**: every change is written to the image's YOLO `.txt` immediately.
- **Undo / redo**: <kbd>Ctrl</kbd>+<kbd>Z</kbd> / <kbd>Ctrl</kbd>+<kbd>Y</kbd>.
- **Copy / paste boxes**: <kbd>Ctrl</kbd>+<kbd>C</kbd> / <kbd>Ctrl</kbd>+<kbd>V</kbd>, useful for consecutive video frames.
- **Select all**: <kbd>Ctrl</kbd>+<kbd>A</kbd>.
- **Mark as Null** (<kbd>N</kbd>): records that the image has nothing to label, so it counts as done.

## View controls

- **Zoom** <kbd>+</kbd> / <kbd>-</kbd>, **fit** <kbd>F</kbd>, and **lock zoom** <kbd>L</kbd> to keep the same zoom across images.
- **Grid overlay** (<kbd>G</kbd>) with adjustable cell size.
- **Show / hide labels** (<kbd>T</kbd>).
- **Brightness and contrast** sliders for dark or washed-out images.
- **Box style**: border width and fill opacity.

## Media library

- Thumbnail sidebar with **paging** (50, 100 or 200 per page).
- Filter by **annotated / unannotated / null**, by **class** and by **tag**.
- **Annotation progress** bar for the current job.
- Set any image as the project's **cover photo**.

When several people work on the same project, opening an image **locks** it to you; see [Teams & permissions](teams.md#image-locks).
