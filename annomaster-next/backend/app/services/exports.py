"""
Dataset exporters — YOLO / COCO / VOC.

Every exporter reads boxes from the CONFIRMED source only (the `.txt`, or a
version's frozen manifest which itself came from the `.txt`). The
`.suggestions.json` sidecar is never touched, so an unreviewed prediction can
never appear in an export — this is enforced by construction, not by filtering.
"""
import io
import json
import zipfile
from pathlib import Path

FORMATS = ('yolo', 'coco', 'voc')


def _yolo_line(b: dict) -> str | None:
    cls = b.get('class_id', b.get('cls'))
    if cls is None:
        return None
    if b.get('type') == 'polygon':
        pts = b.get('points') or []
        if len(pts) < 3:
            return None
        flat = ' '.join(f'{p["x"]:.6f} {p["y"]:.6f}' for p in pts)
        return f'{int(cls)} {flat}'
    try:
        return (f'{int(cls)} {float(b["x_center"]):.6f} {float(b["y_center"]):.6f} '
                f'{float(b["width"]):.6f} {float(b["height"]):.6f}')
    except (KeyError, TypeError, ValueError):
        return None


def _img_size(data: bytes) -> tuple[int, int]:
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            return im.size            # (w, h)
    except Exception:
        return (0, 0)


def build_zip(fmt: str, items: list[dict], class_names: list[str], pdir: Path) -> bytes:
    """
    items: [{rel_path, filename, split, labels:[box…]}]. Returns ZIP bytes.
    Missing image files are skipped (a deleted image can't be exported).
    """
    if fmt not in FORMATS:
        raise ValueError(f'format must be one of {FORMATS}')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        if fmt == 'yolo':
            _build_yolo(z, items, class_names, pdir)
        elif fmt == 'coco':
            _build_coco(z, items, class_names, pdir)
        else:
            _build_voc(z, items, class_names, pdir)
    return buf.getvalue()


def _read_img(pdir: Path, rel_path: str) -> bytes | None:
    p = pdir / rel_path
    return p.read_bytes() if p.exists() else None


# ── YOLO ──────────────────────────────────────────────────────────────────────
def _build_yolo(z, items, class_names, pdir):
    for it in items:
        data = _read_img(pdir, it['rel_path'])
        if data is None:
            continue
        split = it.get('split') or 'train'
        stem = Path(it['filename']).stem
        z.writestr(f'images/{split}/{it["filename"]}', data)
        lines = [ln for b in it['labels'] if (ln := _yolo_line(b))]
        z.writestr(f'labels/{split}/{stem}.txt', ('\n'.join(lines) + '\n') if lines else '')
    yaml = ['train: images/train', 'val: images/valid', 'test: images/test',
            f'nc: {len(class_names)}', 'names:']
    yaml += [f'  {i}: {n}' for i, n in enumerate(class_names)]
    z.writestr('data.yaml', '\n'.join(yaml) + '\n')


# ── COCO (one annotations.json per split) ────────────────────────────────────
def _build_coco(z, items, class_names, pdir):
    per_split: dict[str, dict] = {}
    ann_id = 1
    img_id = 1
    for it in items:
        data = _read_img(pdir, it['rel_path'])
        if data is None:
            continue
        split = it.get('split') or 'train'
        w, h = _img_size(data)
        coco = per_split.setdefault(split, {
            'images': [], 'annotations': [],
            'categories': [{'id': i, 'name': n} for i, n in enumerate(class_names)],
        })
        z.writestr(f'{split}/images/{it["filename"]}', data)
        coco['images'].append({'id': img_id, 'file_name': it['filename'],
                               'width': w, 'height': h})
        for b in it['labels']:
            if b.get('type') == 'polygon':
                continue                      # COCO bbox export: skip polygons here
            try:
                bw, bh = float(b['width']) * w, float(b['height']) * h
                x = float(b['x_center']) * w - bw / 2
                y = float(b['y_center']) * h - bh / 2
            except (KeyError, TypeError, ValueError):
                continue
            coco['annotations'].append({
                'id': ann_id, 'image_id': img_id,
                'category_id': int(b.get('class_id', b.get('cls', 0))),
                'bbox': [round(x, 2), round(y, 2), round(bw, 2), round(bh, 2)],
                'area': round(bw * bh, 2), 'iscrowd': 0})
            ann_id += 1
        img_id += 1
    for split, coco in per_split.items():
        z.writestr(f'{split}/annotations.json', json.dumps(coco))


# ── VOC (per-image XML) ───────────────────────────────────────────────────────
def _build_voc(z, items, class_names, pdir):
    for it in items:
        data = _read_img(pdir, it['rel_path'])
        if data is None:
            continue
        split = it.get('split') or 'train'
        w, h = _img_size(data)
        z.writestr(f'{split}/images/{it["filename"]}', data)
        objs = []
        for b in it['labels']:
            if b.get('type') == 'polygon':
                continue
            try:
                bw, bh = float(b['width']) * w, float(b['height']) * h
                xmin = int(float(b['x_center']) * w - bw / 2)
                ymin = int(float(b['y_center']) * h - bh / 2)
                xmax = int(xmin + bw)
                ymax = int(ymin + bh)
            except (KeyError, TypeError, ValueError):
                continue
            cid = int(b.get('class_id', b.get('cls', 0)))
            cname = class_names[cid] if cid < len(class_names) else str(cid)
            objs.append(f'  <object><name>{cname}</name><bndbox>'
                        f'<xmin>{xmin}</xmin><ymin>{ymin}</ymin>'
                        f'<xmax>{xmax}</xmax><ymax>{ymax}</ymax></bndbox></object>')
        xml = (f'<annotation><filename>{it["filename"]}</filename>'
               f'<size><width>{w}</width><height>{h}</height><depth>3</depth></size>\n'
               + '\n'.join(objs) + '\n</annotation>\n')
        z.writestr(f'{split}/Annotations/{Path(it["filename"]).stem}.xml', xml)
