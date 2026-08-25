# SPDX-License-Identifier: GPL-3.0-or-later
"""Single-instance flock on ``$XDG_RUNTIME_DIR/stenographer.lock``.

``is_lock_contention`` is the pure unit target; mutual exclusion is proven by a
REAL flock on a tmp path (tests/platform/linux/test_lock.py).
"""

from __future__ import annotations

import errno
import fcntl
import os
import pathlib

from stenographer.platform.base import SingleInstanceLockError
from stenographer.platform.linux.dirs import runtime_dir

__all__ = [
    "LOCK_PATH",
    "FlockSingleInstanceLock",
    "SingleInstanceLockError",
    "acquire_single_instance_lock",
    "is_lock_contention",
]


def _default_lock_path() -> pathlib.Path:
    return runtime_dir(os.environ) / "stenographer.lock"


LOCK_PATH = _default_lock_path()


def is_lock_contention(exc: OSError) -> bool:
    """Classify a non-blocking flock failure: contention or real I/O error. PURE.

    Only a lock held elsewhere (EAGAIN/EWOULDBLOCK, per flock(2)) means another
    instance is running; anything else is lock-file I/O gone wrong.
    """
    return exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK)


def acquire_single_instance_lock(path: pathlib.Path = LOCK_PATH) -> int:
    """Take the single-instance flock. Return the held fd, or -1 if another
    open file description already holds it. The PID is written into the file.

    Any lock-file failure that is NOT contention raises
    :class:`SingleInstanceLockError` instead of masquerading as -1.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(fd)
        if is_lock_contention(exc):
            return -1
        raise SingleInstanceLockError(
            f"could not take single-instance lock {path}: "
            f"[{errno.errorcode.get(exc.errno, exc.errno)}] {exc.strerror}"
        ) from exc
    try:
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
    except OSError as exc:
        os.close(fd)  # also releases the flock just taken
        raise SingleInstanceLockError(
            f"could not write pid to lock file {path}: "
            f"[{errno.errorcode.get(exc.errno, exc.errno)}] {exc.strerror}"
        ) from exc
    return fd


class FlockSingleInstanceLock:
    """The daemon's ``SingleInstanceLock``: one flock held for the process lifetime."""

    def __init__(self, path: pathlib.Path = LOCK_PATH) -> None:
        self._path = path
        self._fd = -1

    def acquire(self) -> bool:
        self._fd = acquire_single_instance_lock(self._path)
        return self._fd >= 0

    def release(self) -> None:
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1
