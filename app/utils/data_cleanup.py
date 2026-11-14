"""Remove live tracking rows when their filesystem scope is deleted.

Audit events intentionally remain historical records. Call after successful disk
deletion, then commit together with the caller's workspace/membership changes.
"""
from app import db
from app.models.image import Image
from app.models.assignment import Assignment
from app.models.annotation_lock import AnnotationLock
from app.models.upload_batch import UploadBatch


def clear_tracking(workspace_id, project=None):
    scope = {'workspace_id': workspace_id}
    if project is not None:
        scope['project'] = project
    # Dependents first: assignments and images reference upload batches.
    for model in (Assignment, Image, AnnotationLock, UploadBatch):
        model.query.filter_by(**scope).delete(synchronize_session='fetch')


def close_workspace_indexes(folder_name):
    from app.core.paths import workspace_projects_dir
    from app.core.db_index import close_project
    projects = workspace_projects_dir(folder_name)
    if projects.exists():
        for project in projects.iterdir():
            if project.is_dir():
                close_project(project.resolve())
