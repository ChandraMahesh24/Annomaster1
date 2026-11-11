"""Pydantic models for upload/batch responses."""
from pydantic import BaseModel


class BatchOut(BaseModel):
    upload_id: int
    job_name: str
    source: str
    batch_db_id: int | None = None


class UploadResult(BaseModel):
    success: bool = True
    upload_id: int
    job_name: str
    saved: int = 0
    duplicates: int = 0
    annotated: int = 0


class AssignmentBrief(BaseModel):
    assigned_to: int
    assignee: str
    status: str
    total_images: int
    done_images: int
    progress_pct: int


class BatchListItem(BaseModel):
    upload_id: int
    batch_db_id: int | None = None   # DB id — used to filter the annotator by batch
    job_name: str
    source: str
    total: int
    annotated: int
    pending: int
    null_count: int = 0
    in_dataset: bool = False
    partial_dataset: bool = False
    datetime_str: str | None = None
    uploader_name: str | None = None
    assignment: AssignmentBrief | None = None


class JobEnqueued(BaseModel):
    success: bool = True
    upload_id: int
    job_name: str
    task_id: str | None = None
    mode: str            # 'celery' | 'inline'
    frames_extracted: int | None = None
