"""
Image-level annotation locks.

When a user opens an image for editing they acquire a lock (TTL = 60 s).
The frontend sends a heartbeat every 30 s to renew it.
On navigate-away / close the frontend explicitly releases the lock.
Expired locks are cleaned up lazily on the next acquire call.

This prevents silent last-write-wins data loss when two annotators open
the same image simultaneously.
"""
from datetime import datetime, timedelta
from app import db

LOCK_TTL_SECONDS = 60   # seconds before a lock expires without heartbeat


class AnnotationLock(db.Model):
    __tablename__ = 'annotation_locks'
    __table_args__ = (
        # Only ONE active lock per image per project
        db.UniqueConstraint(
            'workspace_id', 'project', 'image_path',
            name='uq_lock_image'
        ),
        db.Index('ix_lock_expires', 'expires_at'),
        db.Index('ix_lock_workspace_project', 'workspace_id', 'project'),
    )

    id           = db.Column(db.Integer, primary_key=True)
    workspace_id = db.Column(db.Integer, nullable=False)
    project      = db.Column(db.String(200), nullable=False)
    image_path   = db.Column(db.Text, nullable=False)
    locked_by    = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    acquired_at  = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at   = db.Column(db.DateTime, nullable=False)

    locker = db.relationship('User', backref=db.backref('annotation_locks', lazy='dynamic'))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def is_expired(self) -> bool:
        return self.expires_at <= datetime.utcnow()

    def renew(self):
        self.expires_at = datetime.utcnow() + timedelta(seconds=LOCK_TTL_SECONDS)

    def to_dict(self):
        return {
            'locked_by':   self.locked_by,
            'username':    self.locker.username   if self.locker else None,
            'avatar_url':  self.locker.avatar_url if self.locker else None,
            'image_path':  self.image_path,
            'acquired_at': self.acquired_at.isoformat(),
            'expires_at':  self.expires_at.isoformat(),
        }
