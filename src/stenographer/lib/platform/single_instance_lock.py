# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import Protocol


class SingleInstanceLock(Protocol):
    def acquire(self) -> bool:
        """True when held, False on contention; raises SingleInstanceLockError otherwise."""
        ...

    def release(self) -> None: ...
