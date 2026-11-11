"""
Public-ID generator — ported from the original app/utils/id_gen.py.

Formats (unchanged):
    User:      USR-7K3M9P   (prefix + 6 alphanumeric, ambiguous chars removed)
    Workspace: WS-847291    (prefix + 6 digits)

A workspace's public_id doubles as its on-disk folder name, so uniqueness is a
filesystem concern, not just a DB one — enforced by a UNIQUE column plus this
retry-on-collision generator.
"""
import secrets

# O/0 and I/1 removed to avoid visual ambiguity, same as the original.
_ALNUM = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


def _alnum(n: int = 6) -> str:
    return ''.join(secrets.choice(_ALNUM) for _ in range(n))


def _digits(n: int = 6) -> int:
    low, high = 10 ** (n - 1), 10 ** n - 1
    return secrets.randbelow(high - low + 1) + low


def generate_public_id(prefix: str, length: int = 6) -> str:
    if prefix == 'WS':
        return f'{prefix}-{_digits(length)}'
    return f'{prefix}-{_alnum(length)}'


def generate_unique_id(session, model, prefix: str, max_retries: int = 100) -> str:
    """
    A public_id not already present in `model`. Retries on the (negligible)
    collision; the UNIQUE constraint is the real guarantee, this just avoids
    the insert failing.
    """
    for _ in range(max_retries):
        pid = generate_public_id(prefix)
        exists = session.query(model).filter_by(public_id=pid).first()
        if not exists:
            return pid
    raise RuntimeError(f'Could not generate unique {prefix} id after {max_retries} tries')
