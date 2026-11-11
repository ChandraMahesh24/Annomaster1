from datetime import datetime
from app import db

ROLES = ('owner', 'editor', 'viewer')

class Workspace(db.Model):
    __tablename__ = 'workspaces'

    id          = db.Column(db.Integer, primary_key=True)
    public_id   = db.Column(db.String(20), unique=True, nullable=True, index=True)  # WS-XXXXXX
    name        = db.Column(db.String(200), nullable=False)
    folder_name = db.Column(db.String(200), unique=True, nullable=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    members = db.relationship('WorkspaceMember', back_populates='workspace', cascade='all, delete-orphan', lazy='dynamic')

    def to_dict(self, role=None):
        return {
            'id':          self.id,
            'public_id':   self.public_id,
            'name':        self.name,
            'folder_name': self.folder_name,
            'created_at':  self.created_at.isoformat(),
            'role':        role,
        }


class WorkspaceMember(db.Model):
    __tablename__ = 'workspace_members'

    id           = db.Column(db.Integer, primary_key=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=False)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    role         = db.Column(db.String(20), nullable=False, default='viewer')
    joined_at    = db.Column(db.DateTime, default=datetime.utcnow)

    workspace = db.relationship('Workspace', back_populates='members')
    user      = db.relationship('User', back_populates='workspace_memberships')

    __table_args__ = (
        db.UniqueConstraint('workspace_id', 'user_id', name='uq_workspace_user'),
    )

    def to_dict(self):
        return {
            'user_id':       self.user_id,
            'user_public_id': self.user.public_id,
            'username':      self.user.username,
            'email':         self.user.email,
            'role':          self.role,
            'joined_at':     self.joined_at.isoformat(),
            'workspace_id':  self.workspace_id,
        }
