# SPDX-License-Identifier: GPL-3.0-or-later
"""The single-instance flock: pure errno classifier and REAL mutual exclusion.

``is_lock_contention`` was seen to fail against an all-contention stub; the
exclusion test takes a real flock on a tmp path (no mocks, §6.2).
"""

from __future__ import annotations

import errno
import os

from stenographer.platform.linux.lock import (
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
