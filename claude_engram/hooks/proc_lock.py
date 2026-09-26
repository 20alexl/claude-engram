"""A process-lifetime lock: an OS file lock the kernel releases when the
holder exits, however it exits.

The scorer daemon and the background miner used pid files as their
"one instance" guard. A pid file is check-then-write (four miners started
together all acquired it, measured 2026-09-25) and it says nothing about
whether the holder can be reached, so a failed 0.5 s connect was read as a
dead daemon: the files were deleted, a second daemon spawned, and the first
idled for 30 minutes at ~3 GB. Held lock = a live holder; nothing else is
consulted.

stdlib only (msvcrt / fcntl): the hook client runs under ``python -S``.
"""

import os
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class Lock:
    """An acquired lock. ``release()`` or process exit frees it."""

    def __init__(self, path: Path, fd: int):
        self.path = path
        self._fd = fd

    def release(self) -> None:
        if self._fd < 0:
            return
        try:
            if os.name == "nt":
                os.lseek(self._fd, 0, os.SEEK_SET)
                msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(self._fd)
        finally:
            self._fd = -1


def acquire(path) -> "Lock | None":
    """Take the lock at ``path`` without blocking. None when another holder
    (any process, or another handle in this one) has it."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    except OSError:
        return None
    try:
        if os.name == "nt":
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return Lock(path, fd)


def held(path) -> bool:
    """Is a live process holding the lock at ``path``?"""
    lock = acquire(path)
    if lock is None:
        return Path(path).exists()
    lock.release()
    return False
