"""
Dataset membership — add-to-dataset is a DB COLUMN CHANGE, never a file move.

The original physically copied images into Completed_Datasets/. Per the port
spec ("files never move — lifecycle is a DB column"), here an image joins the
dataset by flipping status active→in_dataset and getting a `split`; the file
stays exactly where it was uploaded. Exports read those images from their live
location, so there's no duplicated storage and no move to go wrong.
"""
import random
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.image import Image

SPLITS = ('train', 'valid', 'test')


def add_to_dataset(session: Session, workspace_id: int, project: str,
                   ratios: dict | None = None, rel_paths: list[str] | None = None,
                   seed: int = 42) -> dict:
    """
    Move annotated images into the dataset by assigning a split. No files move.
    `ratios` like {'train':0.7,'valid':0.2,'test':0.1}; defaults to 70/20/10.
    If `rel_paths` given, only those; else every annotated active image.
    """
    ratios = ratios or {'train': 0.7, 'valid': 0.2, 'test': 0.1}
    stmt = select(Image).where(
        Image.workspace_id == workspace_id, Image.project == project,
        Image.status == 'active', Image.is_annotated.is_(True))
    if rel_paths:
        stmt = stmt.where(Image.rel_path.in_(rel_paths))
    images = list(session.scalars(stmt))

    random.Random(seed).shuffle(images)   # deterministic split assignment
    n = len(images)
    n_train = int(n * ratios.get('train', 0.7))
    n_valid = int(n * ratios.get('valid', 0.2))
    assigned = {'train': 0, 'valid': 0, 'test': 0}
    now = datetime.now(timezone.utc)
    for i, img in enumerate(images):
        split = 'train' if i < n_train else 'valid' if i < n_train + n_valid else 'test'
        img.status = 'in_dataset'
        img.split = split
        img.added_to_dataset_at = now
        assigned[split] += 1
    return {'added': n, 'splits': assigned}


def add_batch_to_dataset(session: Session, workspace_id: int, project: str,
                         batch_db_id: int, train_r: float = 0.70,
                         val_r: float = 0.15, test_r: float = 0.15,
                         reviewer_id: int | None = None) -> dict:
    """
    Roboflow-style "Add to Dataset" for ONE batch: only its ANNOTATED (and null-
    marked) images join the dataset; raw/unlabelled images stay in Active Work.
    Files never move — this flips status active→in_dataset and assigns a split.
    Verbatim port of the original core.datasets.add_batch_to_dataset, including
    its min-1-per-split guarantees and the total==1/2 special cases.

    Returns {success, moved_annotated, remaining_raw, split_counts:{train,val,test}}.
    """
    # Images that have a labelling decision (real boxes OR an explicit null mark)
    # and are still active (not already in a dataset).
    imgs = list(session.scalars(select(Image).where(
        Image.workspace_id == workspace_id, Image.project == project,
        Image.batch_id == batch_db_id, Image.status == 'active',
        (Image.is_annotated.is_(True)) | (Image.is_null.is_(True)))))
    remaining_raw = session.scalar(select(func.count()).select_from(
        select(Image).where(
            Image.workspace_id == workspace_id, Image.project == project,
            Image.batch_id == batch_db_id, Image.status == 'active',
            Image.is_annotated.is_(False), Image.is_null.is_(False)).subquery())) or 0

    total = len(imgs)
    if total == 0:
        return {'success': False,
                'error': f'No annotated images in this batch ({remaining_raw} raw). '
                         'Annotate at least one image first.',
                'moved_annotated': 0, 'remaining_raw': remaining_raw,
                'split_counts': {'train': 0, 'val': 0, 'test': 0}}

    random.shuffle(imgs)
    s = train_r + val_r + test_r
    if s > 0:
        train_r /= s
        val_r /= s
    n_train = round(total * train_r)
    n_val = round(total * val_r)
    n_test = total - n_train - n_val
    if total == 1:
        n_train, n_val, n_test = 1, 0, 0
    elif total == 2:
        n_train, n_val, n_test = 1, 0, 1
    else:                                    # total >= 3 → guarantee ≥1 train & val
        n_train = max(1, n_train)
        n_val = max(1, n_val)
        n_test = total - n_train - n_val

    # DB split enum is train|valid|test; the UI/return use train|val|test.
    buckets = [('train', imgs[:n_train]),
               ('valid', imgs[n_train:n_train + n_val]),
               ('test', imgs[n_train + n_val:])]
    now = datetime.now(timezone.utc)
    for db_split, group in buckets:
        for img in group:
            img.status = 'in_dataset'
            img.split = db_split
            img.reviewed_by = reviewer_id
            img.reviewed_at = now
            img.added_to_dataset_at = now
            img.is_annotated = True
    return {'success': True, 'moved_annotated': total, 'remaining_raw': remaining_raw,
            'split_counts': {'train': n_train, 'val': n_val, 'test': n_test}}


def remove_from_dataset(session: Session, workspace_id: int, project: str,
                        rel_paths: list[str] | None = None) -> int:
    stmt = select(Image).where(
        Image.workspace_id == workspace_id, Image.project == project,
        Image.status == 'in_dataset')
    if rel_paths:
        stmt = stmt.where(Image.rel_path.in_(rel_paths))
    imgs = list(session.scalars(stmt))
    for img in imgs:
        img.status = 'active'
        img.split = None
        img.added_to_dataset_at = None
    return len(imgs)


def dataset_summary(session: Session, workspace_id: int, project: str) -> dict:
    rows = session.execute(
        select(Image.split, func.count()).where(
            Image.workspace_id == workspace_id, Image.project == project,
            Image.status == 'in_dataset').group_by(Image.split)).all()
    counts = {s: 0 for s in SPLITS}
    for split, cnt in rows:
        if split in counts:
            counts[split] = cnt
    return {'total': sum(counts.values()), 'splits': counts}


def dataset_images(session: Session, workspace_id: int, project: str) -> list[Image]:
    return list(session.scalars(select(Image).where(
        Image.workspace_id == workspace_id, Image.project == project,
        Image.status == 'in_dataset')))
