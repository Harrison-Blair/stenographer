# SPDX-License-Identifier: GPL-3.0-or-later
"""Process-wide locks that serialize mutating operations on one session."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import ClassVar


class SessionLocks:
    """Give every SessionStore instance the same lock for one session folder."""

    _guard: ClassVar[threading.Lock] = threading.Lock()
    _locks: ClassVar[dict[tuple[Path, str], threading.RLock]] = {}

    @classmethod
    def lock(cls, root: Path, session_id: str) -> threading.RLock:
        key = (Path(root).resolve(strict=False), session_id)
        with cls._guard:
            return cls._locks.setdefault(key, threading.RLock())
