"""
Image — one row per image file in a project.

Files NEVER move on disk. Status changes are tracked here in the DB.
This replaces the file-move (Active_Work → Completed_Datasets) approach.

is_null vs is_annotated explained:
  is_annotated=False, is_null=False  →  not yet worked on (no .txt file)
  is_annotated=True,  is_null=False  →  has bounding boxes (.txt with content)
  is_annotated=True,  is_null=True   →  background image, no objects
                                        (.txt file exists but is EMPTY)
                                        YOLO requires empty .txt for null images,
                                        NOT a missing file.

status values:
  'active'      →  in the annotation queue (Active Work)
  'in_dataset'  →  reviewed and added to the dataset (Completed)

split values (only set when status='in_dataset'):
  'train' | 'val' | 'test'
"""
from datetime import datetime
from app import db


class Image(db.Model):
    __tablename__ = 'images'
    __table_args__ = (
        db.Index('ix_image_workspace_project', 'workspace_id', 'project'),
        db.Index('ix_image_batch_id',          'batch_id'),
        db.Index('ix_image_status',            'status'),
        db.Index('ix_image_annotated_by',      'annotated_by'),
        db.Index('ix_image_assigned_to',       'assigned_to'),
    )

    id           = db.Column(db.Integer, primary_key=True)
    workspace_id = db.Column(db.Integer, nullable=False)
    project      = db.Column(db.String(200), nullable=False)
    batch_id     = db.Column(
        db.Integer,
        db.ForeignKey('upload_batches.id', ondelete='SET NULL'),
        nullable=True,
    )

    filename     = db.Column(db.String(500), nullable=False)
    rel_path     = db.Column(db.Text, nullable=False)  # NEVER changes after insert

    # ── Stage ────────────────────────────────────────────────────────────────
    status       = db.Column(db.String(20), default='active',  nullable=False)
    split        = db.Column(db.String(10), nullable=True)     # train/val/test

    # ── Annotation state ──────────────────────────────────────────────────────
    is_annotated = db.Column(db.Boolean, default=False, nullable=False)
    is_null      = db.Column(db.Boolean, default=False, nullable=False)
    # is_null=True  → background image, empty .txt written, counts as "done"
    # is_null=False → normal image; is_annotated=True means .txt has bbox lines

    # ── Who did what ──────────────────────────────────────────────────────────
    uploaded_by  = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    uploaded_at  = db.Column(db.DateTime, default=datetime.utcnow)

    annotated_by = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    annotated_at = db.Column(db.DateTime, nullable=True)

    reviewed_by  = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    reviewed_at          = db.Column(db.DateTime, nullable=True)
    added_to_dataset_at  = db.Column(db.DateTime, nullable=True)

    # assignment shortcut — which user is currently responsible for this image
    assigned_to  = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    batch      = db.relationship('UploadBatch', back_populates='images')
    uploader   = db.relationship('User', foreign_keys=[uploaded_by],
                                 backref=db.backref('uploaded_images',   lazy='dynamic'))
    annotator  = db.relationship('User', foreign_keys=[annotated_by],
                                 backref=db.backref('annotated_images',  lazy='dynamic'))
    reviewer   = db.relationship('User', foreign_keys=[reviewed_by],
                                 backref=db.backref('reviewed_images',   lazy='dynamic'))
    assignee   = db.relationship('User', foreign_keys=[assigned_to],
                                 backref=db.backref('assigned_images',   lazy='dynamic'))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def mark_annotated(self, user_id: int, is_null: bool = False):
        """Call this after a successful annotation save (or null-mark)."""
        self.is_annotated = True
        self.is_null      = is_null
        self.annotated_by = user_id
        self.annotated_at = datetime.utcnow()

    def mark_in_dataset(self, split: str, reviewer_id: int | None = None):
        """Move to dataset (reviewed + accepted). Files stay on disk — only DB changes."""
        self.status             = 'in_dataset'
        self.split              = split
        self.reviewed_by        = reviewer_id
        self.reviewed_at        = datetime.utcnow()
        self.added_to_dataset_at = datetime.utcnow()

    def to_dict(self):
        return {
            'id':            self.id,
            'workspace_id':  self.workspace_id,
            'project':       self.project,
            'batch_id':      self.batch_id,
            'filename':      self.filename,
            'rel_path':      self.rel_path,
            'status':        self.status,
            'split':         self.split,
            'is_annotated':  self.is_annotated,
            'is_null':       self.is_null,
            'uploaded_by':   self.uploaded_by,
            'uploader':      self.uploader.username  if self.uploader  else None,
            'uploaded_at':   self.uploaded_at.isoformat() if self.uploaded_at else None,
            'annotated_by':  self.annotated_by,
            'annotator':     self.annotator.username if self.annotator else None,
            'annotated_at':  self.annotated_at.isoformat() if self.annotated_at else None,
            'reviewed_by':          self.reviewed_by,
            'reviewer':             self.reviewer.username  if self.reviewer  else None,
            'reviewed_at':          self.reviewed_at.isoformat() if self.reviewed_at else None,
            'added_to_dataset_at':  self.added_to_dataset_at.isoformat() if self.added_to_dataset_at else None,
            'assigned_to':          self.assigned_to,
            'assignee':             self.assignee.username  if self.assignee  else None,
        }
