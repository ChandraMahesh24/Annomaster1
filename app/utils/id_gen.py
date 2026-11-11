"""
Public ID generator — professional, human-readable unique identifiers.

Formats:
  User:      USR-7K3M9P   (prefix + 6 alphanumeric = 2.1B+ combos)
  Workspace: WS-847291     (prefix + 6 digits = 900K combos)

These are display IDs shown in the UI and API responses.
The internal integer `id` is still used for DB joins/foreign keys.
"""
import secrets
import string


def _random_alphanum(length: int = 6) -> str:
    """Generate uppercase alphanumeric string (no ambiguous chars O/0, I/1)."""
    chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # removed O,0,I,1 to avoid confusion
    return ''.join(secrets.choice(chars) for _ in range(length))


def _random_digits(length: int = 6) -> int:
    """Generate a random N-digit number (never starts with 0)."""
    low  = 10 ** (length - 1)       # 100000
    high = 10 ** length - 1          # 999999
    return secrets.randbelow(high - low + 1) + low


def generate_public_id(prefix: str, length: int = 6) -> str:
    """
    Generate a public ID with the given prefix.

    Examples:
      generate_public_id('USR')  → 'USR-7K3M9P'
      generate_public_id('WS')   → 'WS-847291'
    """
    if prefix == 'WS':
        return f'{prefix}-{_random_digits(length)}'
    else:
        return f'{prefix}-{_random_alphanum(length)}'


def generate_unique_id(model_class, prefix: str, length: int = 6,
                       max_retries: int = 100) -> str:
    """
    Generate a unique public ID that doesn't already exist in the DB.

    Collision probability is negligible (6 alphanumeric = 2.1B combos),
    but we retry just in case.
    """
    for _ in range(max_retries):
        pid = generate_public_id(prefix, length)
        if not model_class.query.filter_by(public_id=pid).first():
            return pid
    raise RuntimeError(
        f'Could not generate unique {prefix} ID after {max_retries} attempts'
    )
