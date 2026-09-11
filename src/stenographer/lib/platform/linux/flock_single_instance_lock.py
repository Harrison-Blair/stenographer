# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import os
import pathlib

from stenographer.lib.platform.linux.lock import LOCK_PATH, acquire_single_instance_lock


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
