"""
Atomic file writes that survive Windows.

`os.replace(tmp, path)` is atomic on every platform, BUT on Windows it raises
PermissionError (WinError 5 "access denied" / WinError 32 "used by another
process") when the destination is *briefly* held open by:
  • a concurrent reader (e.g. a GET reading the label .txt), or
  • a concurrent writer's own replace, or
  • antivirus / the search indexer scanning the just-written temp file.

Annotations auto-save (debounced save + flush-on-navigation) can fire two writes
to the SAME label file within milliseconds, which is exactly this case — and it
surfaced as a 500. The fix is to RETRY the replace with a short backoff; the lock
is transient and clears in well under a second. Content is unaffected: os.replace
is still atomic, so a reader always sees either the old or the new file whole.
"""
import os
import time
import uuid
from pathlib import Path

# ~1.3s worst case (0.03·(1+2+…+8)); real transient locks clear in <100ms.
_RETRIES = 8
_BASE_DELAY = 0.03


def atomic_write(path: Path, data: "str | bytes", encoding: str = 'utf-8') -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f'.{uuid.uuid4().hex[:8]}.tmp')
    try:
        if isinstance(data, str):
            tmp.write_text(data, encoding=encoding)
        else:
            tmp.write_bytes(data)
        last: Exception | None = None
        for i in range(_RETRIES):
            try:
                os.replace(tmp, path)
                return
            except PermissionError as e:      # WinError 5 / 32 — transient lock
                last = e
                time.sleep(_BASE_DELAY * (i + 1))
        if last:                              # exhausted retries — re-raise
            raise last
    finally:
        Path(tmp).unlink(missing_ok=True)
