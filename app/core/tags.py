"""
Batch and dataset tags — free-form labels used to filter Active Work and
Completed Datasets, in the spirit of Roboflow's tags.

WHERE THEY LIVE
───────────────
Batch tags are stored **inside the batch record in `_uploads.json`**, not in a
side table. That record is already the batch's source of truth, and
`api_uploads` spreads it straight into the response — so tags travel with the
batch for free, and are deleted with it. No migration, no orphan rows.

Dataset tags have no such record (a dataset is either derived from DB rows as
`db_<batch_id>` or is a Completed_Datasets folder), so they go in a project-
level `_tags.json` keyed by dataset_id — see paths.tags_meta_file.

MATCHING RULES
──────────────
Tags are compared case-insensitively but stored with the case the user typed:
"Blurry" and "blurry" are one tag, and it displays the way they first wrote it.
Commas are stripped because the input treats them as separators.
"""
from app.core.storage import (load_json, load_uploads, save_json, save_uploads)

MAX_TAG_LEN   = 32
MAX_PER_ITEM  = 12


def normalize(tag: str) -> str:
    """Clean a single tag, or return '' if it isn't usable."""
    tag = (tag or '').replace(',', ' ').strip()
    tag = ' '.join(tag.split())          # collapse internal whitespace
    return tag[:MAX_TAG_LEN]


def clean_list(tags) -> list:
    """Normalize, drop blanks, de-duplicate case-insensitively, cap the count."""
    if not isinstance(tags, (list, tuple)):
        return []
    out, seen = [], set()
    for t in tags:
        t = normalize(t if isinstance(t, str) else '')
        if not t:
            continue
        k = t.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
        if len(out) >= MAX_PER_ITEM:
            break
    return out


# ── Batch tags (inside _uploads.json) ─────────────────────────────────────────

def set_batch_tags(ws_folder: str, project: str, upload_id: int, tags) -> list:
    """Replace one batch's tags. Returns the cleaned list, or None if no such
    batch — the caller turns that into a 404."""
    cleaned = clean_list(tags)
    batches = load_uploads(ws_folder, project)
    found   = False
    for b in batches:
        if b.get('upload_id') == upload_id:
            b['tags'] = cleaned
            found = True
            break
    if not found:
        return None
    save_uploads(ws_folder, project, batches)
    return cleaned


# ── Dataset tags (project-level _tags.json) ───────────────────────────────────

def _load(ws_folder: str, project: str) -> dict:
    from app.core.paths import tags_meta_file
    data = load_json(tags_meta_file(ws_folder, project), {})
    return data if isinstance(data, dict) else {}


def dataset_tags_map(ws_folder: str, project: str) -> dict:
    """{dataset_id: [tags]} — used to decorate the dataset list."""
    d = _load(ws_folder, project).get('datasets', {})
    return d if isinstance(d, dict) else {}


def set_dataset_tags(ws_folder: str, project: str, dataset_id: str, tags) -> list:
    from app.core.paths import tags_meta_file
    cleaned = clean_list(tags)
    data    = _load(ws_folder, project)
    ds      = data.get('datasets')
    if not isinstance(ds, dict):
        ds = {}
    if cleaned:
        ds[dataset_id] = cleaned
    else:
        ds.pop(dataset_id, None)     # empty list = untagged, don't keep a key
    data['datasets'] = ds
    save_json(tags_meta_file(ws_folder, project), data)
    return cleaned


# ── Catalogue ─────────────────────────────────────────────────────────────────

def all_tags(ws_folder: str, project: str) -> list:
    """
    Every distinct tag used anywhere in the project, sorted. Drives the filter
    dropdowns and the add-tag suggestions, so the user picks an existing tag
    instead of creating a near-duplicate.
    """
    seen, out = set(), []
    def _add(tags):
        for t in tags or []:
            k = str(t).lower()
            if k not in seen:
                seen.add(k)
                out.append(str(t))

    for b in load_uploads(ws_folder, project):
        _add(b.get('tags'))
    for tags in dataset_tags_map(ws_folder, project).values():
        _add(tags)
    return sorted(out, key=str.lower)
