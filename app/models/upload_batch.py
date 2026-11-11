"""
Upload batch — one record per bulk upload operation.

Every time a user uploads images (drag-drop, folder, ZIP, or video extract)
a new UploadBatch row is created. All images from that upload reference this
batch via batch_id so you can always answer:
  • Who uploaded this group of images?
  • When did it arrive?
  • How many images are in it?
"""
from datetime import datetime
from app import db


class UploadBatch(db.Model):
    __tablename__ = 'upload_batches'
    __table_args__ = (
        db.Index('ix_batch_workspace_project', 'workspace_id', 'project'),
        db.Index('ix_batch_uploaded_by',       'uploaded_by'),
    )

    id           = db.Column(db.Integer, primary_key=True)
    workspace_id = db.Column(db.Integer, nullable=False)
    project      = db.Column(db.String(200), nullable=False)
    batch_name   = db.Column(db.String(200), nullable=True)   # optional label e.g. "Site-A Day-1"
    source       = db.Column(db.String(50),  default='upload')
                             # 'upload' | 'folder' | 'zip' | 'video'
    uploaded_by  = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    uploaded_at  = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    total_images = db.Column(db.Integer,  default=0, nullable=False)

    uploader = db.relationship(
        'User',
        backref=db.backref('upload_batches', lazy='dynamic'),
        foreign_keys=[uploaded_by],
    )
    images = db.relationship('Image', back_populates='batch', lazy='dynamic')

    def to_dict(self):
        return {
            'id':           self.id,
            'workspace_id': self.workspace_id,
            'project':      self.project,
            'batch_name':   self.batch_name,
            'source':       self.source,
            'uploaded_by':  self.uploaded_by,
            'uploader':     self.uploader.username if self.uploader else None,
            'uploaded_at':  self.uploaded_at.isoformat(),
            'total_images': self.total_images,
        }
