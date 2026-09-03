"""Interprocess exclusive file lock for agent JSON stores (Windows + POSIX)."""

from __future__ import annotations

import logging
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

_LOCK_POLL_SEC = 0.05
_LOCK_WAIT_SEC = 15.0


@contextmanager
def interprocess_file_lock(path: Path, *, label: str = "agent file") -> Iterator[None]:
    """Exclusive lock across FastAPI workers / processes for one logical file.

    Uses a sibling ``*.lock`` file; ``path`` need not exist yet.
    """
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as handle:
        deadline = time.monotonic() + _LOCK_WAIT_SEC
        locked = False
        while time.monotonic() < deadline:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError:
                time.sleep(_LOCK_POLL_SEC)
        if not locked:
            raise TimeoutError(f"{label} 锁超时: {path}")
        try:
            yield
        finally:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                logger.warning("Failed to release %s lock %s", label, lock_path)
