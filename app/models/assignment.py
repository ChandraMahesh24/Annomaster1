"""
Assignment — owner assigns a batch (or subset of images) to an annotator.

Lifecycle:
  pending      →  annotator has not started yet
  in_progress  →  annotator opened at least one image
  submitted    →  annotator clicked "Submit for review"
  approved     →  owner accepted; images can now be added to dataset
  rejected     →  owner sent back for rework; annotator must fix and resubmit

done_images is incremented by the annotation save endpoint each time an image
in this assignment is annotated (or marked null) for the first time.
"""
from datetime import datetime
from app import db

VALID_STATUSES = ('pending', 'in_progress', 'submitted', 'approved', 'rejected')


class Assignment(db.Model):
    __tablename__ = 'assignments'
    __table_args__ = (
        db.Index('ix_assignment_workspace_project', 'workspace_id', 'project'),
        db.Index('ix_assignment_assigned_to',       'assigned_to'),
        db.Index('ix_assignment_batch_id',          'batch_id'),
        db.Index('ix_assignment_status',            'status'),
    )

    id           = db.Column(db.Integer, primary_key=True)
    workspace_id = db.Column(db.Integer, nullable=False)
    project      = db.Column(db.String(200), nullable=False)
    batch_id     = db.Column(
        db.Integer,
        db.ForeignKey('upload_batches.id', ondelete='CASCADE'),
        nullable=True,
    )

    assigned_to  = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    assigned_by  = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    assigned_at  = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    due_date     = db.Column(db.DateTime, nullable=True)
    note         = db.Column(db.Text,     nullable=True)

    status       = db.Column(db.String(20), default='pending', nullable=False)

    total_images = db.Column(db.Integer, default=0, nullable=False)
    done_images  = db.Column(db.Integer, default=0, nullable=False)

    # ── Relationships ─────────────────────────────────────────────────────────
    assignee = db.relationship(
        'User', foreign_keys=[assigned_to],
        backref=db.backref('assignments_received', lazy='dynamic'),
    )
    assigner = db.relationship(
        'User', foreign_keys=[assigned_by],
        backref=db.backref('assignments_given', lazy='dynamic'),
    )
    batch = db.relationship(
        'UploadBatch',
        backref=db.backref('assignments', lazy='dynamic'),
    )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @property
    def progress_pct(self) -> float:
        if not self.total_images:
            return 0.0
        return round(self.done_images * 100.0 / self.total_images, 1)

    def record_image_done(self):
        """Call each time an image in this assignment is annotated for the first time."""
        if self.done_images < self.total_images:
            self.done_images += 1
        if self.status == 'pending':
            self.status = 'in_progress'
        if self.done_images >= self.total_images and self.status == 'in_progress':
            self.status = 'submitted'

    def to_dict(self):
        return {
            'id':            self.id,
            'workspace_id':  self.workspace_id,
            'project':       self.project,
            'batch_id':      self.batch_id,
            'batch_name':    self.batch.batch_name if self.batch else None,
            'assigned_to':   self.assigned_to,
            'assignee':      self.assignee.username  if self.assignee else None,
            'assigned_by':   self.assigned_by,
            'assigner':      self.assigner.username  if self.assigner  else None,
            'assigned_at':   self.assigned_at.isoformat(),
            'due_date':      self.due_date.isoformat() if self.due_date else None,
            'note':          self.note,
            'status':        self.status,
            'total_images':  self.total_images,
            'done_images':   self.done_images,
            'progress_pct':  self.progress_pct,
        }
