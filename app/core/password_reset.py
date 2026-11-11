"""
Password reset — stateless, single-use tokens.

A reset token is an itsdangerous signature (keyed on SECRET_KEY) over
``{uid, ph}``, where ``ph`` is a short hash of the user's *current*
password_hash. That gives us, with no new table or migration:

* expiry       — ``max_age`` on load (RESET_TOKEN_MINUTES, default 30);
* single use   — setting a new password changes password_hash, so ``ph``
                 no longer matches and the same link is dead;
* revocation   — any password change (Settings, another reset) kills
                 every outstanding link for that user.

Delivery: if ``MAIL_SERVER`` is configured the link is emailed over SMTP;
otherwise it is written to the server log so an admin can hand it over.
Sending happens on a background thread so response time does not reveal
whether the address belongs to an account.
"""
import hashlib
import smtplib
import threading
from email.message import EmailMessage

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.utils.logger import get_logger

log = get_logger(__name__)

_SALT = 'annomaster.password-reset'


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt=_SALT)


def _fingerprint(password_hash: str) -> str:
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def token_minutes() -> int:
    return int(current_app.config.get('RESET_TOKEN_MINUTES', 30))


def make_token(user) -> str:
    return _serializer().dumps({'uid': user.id, 'ph': _fingerprint(user.password_hash)})


def verify_token(token: str):
    """Return the User a valid token belongs to, else None."""
    from app import db
    from app.models.user import User
    try:
        data = _serializer().loads(token, max_age=token_minutes() * 60)
    except (SignatureExpired, BadSignature):
        return None
    user = db.session.get(User, int(data.get('uid') or 0))
    if not user or not user.is_active:
        return None
    if data.get('ph') != _fingerprint(user.password_hash):
        return None   # already used, or password changed since it was issued
    return user


def send_reset_link(user, link: str) -> None:
    """Email the link if SMTP is configured, otherwise log it. Never raises."""
    cfg = current_app.config
    if not cfg.get('MAIL_SERVER'):
        log.warning('Password reset requested for %s — no MAIL_SERVER configured, '
                    'link: %s', user.email, link)
        return

    minutes = token_minutes()
    msg = EmailMessage()
    msg['Subject'] = 'Reset your AnnoMaster password'
    msg['From'] = cfg.get('MAIL_FROM') or cfg.get('MAIL_USERNAME')
    msg['To'] = user.email
    msg.set_content(
        f'Hi {user.username},\n\n'
        f'Someone asked to reset the password for your AnnoMaster account.\n'
        f'Open this link within {minutes} minutes to choose a new one:\n\n'
        f'{link}\n\n'
        f"If this wasn't you, ignore this email — your password won't change.\n"
    )
    smtp = dict(
        host=cfg['MAIL_SERVER'], port=int(cfg.get('MAIL_PORT', 587)),
        user=cfg.get('MAIL_USERNAME'), password=cfg.get('MAIL_PASSWORD'),
        tls=bool(cfg.get('MAIL_USE_TLS', True)),
    )

    def _send():
        try:
            with smtplib.SMTP(smtp['host'], smtp['port'], timeout=20) as s:
                if smtp['tls']:
                    s.starttls()
                if smtp['user']:
                    s.login(smtp['user'], smtp['password'] or '')
                s.send_message(msg)
            log.info('Password reset email sent to %s', user.email)
        except Exception as e:
            log.error('Password reset email to %s failed: %s', user.email, e)

    threading.Thread(target=_send, daemon=True).start()
