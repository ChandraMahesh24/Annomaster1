from datetime import datetime, timedelta
from app import db
from werkzeug.security import generate_password_hash, check_password_hash

MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES   = 15


class User(db.Model):
    __tablename__ = 'users'

    id                 = db.Column(db.Integer, primary_key=True)
    public_id          = db.Column(db.String(20), unique=True, nullable=True, index=True)  # USR-XXXXXX
    email              = db.Column(db.String(255), unique=True, nullable=False, index=True)
    username           = db.Column(db.String(100), unique=True, nullable=False)
    password_hash      = db.Column(db.String(255), nullable=False)
    avatar_url         = db.Column(db.String(500), nullable=True)
    bio                = db.Column(db.String(500), nullable=True)
    created_at         = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at         = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login         = db.Column(db.DateTime, nullable=True)
    is_active          = db.Column(db.Boolean, default=True, nullable=False)
    # Brute-force lockout
    failed_login_count = db.Column(db.Integer, default=0, nullable=False)
    locked_until       = db.Column(db.DateTime, nullable=True)

    workspace_memberships = db.relationship(
        'WorkspaceMember', back_populates='user', lazy='dynamic'
    )

    # ── Password ──────────────────────────────────────────────────────────────

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    # ── Lockout helpers ───────────────────────────────────────────────────────

    def is_locked(self) -> bool:
        return bool(self.locked_until and self.locked_until > datetime.utcnow())

    def lockout_remaining_minutes(self) -> int:
        if not self.is_locked():
            return 0
        delta = self.locked_until - datetime.utcnow()
        return max(1, int(delta.total_seconds() / 60) + 1)

    def record_failed_login(self):
        self.failed_login_count = (self.failed_login_count or 0) + 1
        if self.failed_login_count >= MAX_FAILED_LOGINS:
            self.locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)

    def record_successful_login(self):
        self.failed_login_count = 0
        self.locked_until       = None
        self.last_login         = datetime.utcnow()

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self, include_private=False):
        d = {
            'id':         self.id,
            'public_id':  self.public_id,
            'email':      self.email,
            'username':   self.username,
            'avatar_url': self.avatar_url,
            'bio':        self.bio,
            'created_at': self.created_at.isoformat(),
            'last_login': self.last_login.isoformat() if self.last_login else None,
        }
        if include_private:
            d['is_active']          = self.is_active
            d['failed_login_count'] = self.failed_login_count
            d['locked_until']       = self.locked_until.isoformat() if self.locked_until else None
        return d
