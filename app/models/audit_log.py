"""
Audit log — immutable record of every significant action taken by any user.
Written on: annotation saves, class changes, member invites, login events,
            version creation, dataset exports, and account changes.
"""
import json
from datetime import datetime
from app import db


class AuditLog(db.Model):
    __tablename__ = 'audit_log'
    __table_args__ = (
        db.Index('ix_audit_workspace_project', 'workspace_id', 'project'),
        db.Index('ix_audit_user_id',           'user_id'),
        db.Index('ix_audit_timestamp',         'timestamp'),
        db.Index('ix_audit_action',            'action'),
    )

    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer,
                             db.ForeignKey('users.id', ondelete='SET NULL'),
                             nullable=True, index=True)
    action       = db.Column(db.String(80), nullable=False)   # e.g. 'annotation.save'
    workspace_id = db.Column(db.Integer,   nullable=True)
    project      = db.Column(db.String(200), nullable=True)
    image_path   = db.Column(db.Text,      nullable=True)
    detail       = db.Column(db.Text,      nullable=True)     # JSON blob
    ip_address   = db.Column(db.String(50), nullable=True)
    timestamp    = db.Column(db.DateTime,  default=datetime.utcnow, nullable=False)

    user = db.relationship('User', backref=db.backref('audit_logs', lazy='dynamic'))

    def to_dict(self):
        return {
            'id':           self.id,
            'user_id':      self.user_id,
            'username':     self.user.username if self.user else None,
            'avatar_url':   self.user.avatar_url if self.user else None,
            'action':       self.action,
            'workspace_id': self.workspace_id,
            'project':      self.project,
            'image_path':   self.image_path,
            'detail':       json.loads(self.detail) if self.detail else None,
            'ip_address':   self.ip_address,
            'timestamp':    self.timestamp.isoformat(),
        }


# ── Convenience helper ────────────────────────────────────────────────────────

def log_action(
    action: str,
    *,
    user_id:      int  | None = None,
    workspace_id: int  | None = None,
    project:      str  | None = None,
    image_path:   str  | None = None,
    detail:       dict | None = None,
    ip:           str  | None = None,
):
    """
    Write one audit log row.  Fire-and-forget — swallows all exceptions so a
    logging failure never breaks the caller's response.
    """
    try:
        entry = AuditLog(
            user_id=user_id,
            action=action,
            workspace_id=workspace_id,
            project=project,
            image_path=image_path,
            detail=json.dumps(detail, default=str) if detail else None,
            ip_address=ip,
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
