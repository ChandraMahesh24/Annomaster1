"""
All ORM models, re-exported so a single `import app.models` populates
`Base.metadata` for Alembic autogenerate and create_all.
"""
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.models.upload_batch import UploadBatch
from app.models.image import Image
from app.models.assignment import Assignment
from app.models.annotation_lock import AnnotationLock
from app.models.audit_log import AuditLog

__all__ = [
    'User', 'Workspace', 'WorkspaceMember', 'UploadBatch', 'Image',
    'Assignment', 'AnnotationLock', 'AuditLog',
]
