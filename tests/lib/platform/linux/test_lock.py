# SPDX-License-Identifier: GPL-3.0-or-later
"""The single-instance flock: pure errno classifier and REAL mutual exclusion.

``is_lock_contention`` was seen to fail against an all-contention stub; the
exclusion test takes a real flock on a tmp path (no mocks).
"""

from __future__ import annotations

import errno
import os

from stenographer.lib.platform.linux.lock import (
    LOCK_PATH,
    SingleInstanceLockError,
    acquire_single_instance_lock,
    is_lock_contention,
)


def test_is_lock_contention_classifies_errnos():
    # Only a held flock is contention (EAGAIN/EWOULDBLOCK — the same value on
    # Linux, both spelled out per the flock(2) contract); disk-full or I/O
    # failure on the lock file must surface as an error, never as "another
    # instance is already running". Seen to fail against an always-True stub
    # (today's policy of swallowing every OSError as contention).
    assert is_lock_contention(OSError(errno.EAGAIN, "held")) is True
    assert is_lock_contention(OSError(errno.EWOULDBLOCK, "held")) is True
    assert is_lock_contention(OSError(errno.ENOSPC, "disk full")) is False
    assert is_lock_contention(OSError(errno.EIO, "io error")) is False
    assert is_lock_contention(OSError(errno.EACCES, "denied")) is False
    # The non-contention escape hatch is still an OSError for callers that
    # only catch broadly.
    assert issubclass(SingleInstanceLockError, OSError)


def test_single_instance_lock_is_mutually_exclusive(tmp_path):
    lock = tmp_path / "stenographer.lock"
    fd = acquire_single_instance_lock(lock)
    assert fd >= 0
    inode = lock.stat().st_ino
    # The PID is recorded in the lock file.
    assert lock.read_text().strip() == str(os.getpid())
    # A second acquire against the SAME path is a distinct open file description,
    # so its non-blocking flock contends even in-process and returns -1.
    assert acquire_single_instance_lock(lock) == -1
    os.close(fd)

    # Release keeps the inode at the stable path; the next owner rewrites the
    # PID in place, and a third contender still conflicts on the same inode.
    assert lock.exists()
    next_fd = acquire_single_instance_lock(lock)
    assert next_fd >= 0
    try:
        assert lock.stat().st_ino == inode
        assert lock.read_text().strip() == str(os.getpid())
        assert acquire_single_instance_lock(lock) == -1
    finally:
        os.close(next_fd)


def test_flock_single_instance_lock_excludes_a_second_holder_until_released(tmp_path):
    """The daemon's lock object over a REAL flock on a tmp path.

    Two instances against the same path are two open file descriptions, so the
    second contends in-process exactly as a second daemon would. Release is
    proven by what it enables — the loser can then take the lock — rather than
    by inspecting the descriptor.
    """
    from stenographer.lib.platform.linux.flock_single_instance_lock import FlockSingleInstanceLock

    path = tmp_path / "stenographer.lock"
    first = FlockSingleInstanceLock(path)
    second = FlockSingleInstanceLock(path)

    assert first.acquire() is True
    assert second.acquire() is False
    assert path.read_text().strip() == str(os.getpid())

    first.release()
    assert second.acquire() is True
    try:
        assert FlockSingleInstanceLock(path).acquire() is False
    finally:
        second.release()
        # Releasing an unheld lock is a no-op, so daemon shutdown may be
        # unwound twice without closing an fd it no longer owns.
        second.release()

    third = FlockSingleInstanceLock(path)
    assert third.acquire() is True
    third.release()


def test_flock_single_instance_lock_defaults_to_the_runtime_lock_path():
    # The default is the shared runtime path, so two daemons contend without
    # either being told where the lock lives. Nothing is acquired here.
    from stenographer.lib.platform.linux.flock_single_instance_lock import FlockSingleInstanceLock

    assert FlockSingleInstanceLock()._path == LOCK_PATH
