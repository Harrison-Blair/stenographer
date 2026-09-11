# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import Protocol


class HotkeyListener(Protocol):
    """What ``Daemon`` uses of a listener (start/stop/release guard)."""

    def start(self) -> None: ...

    def stop(self, timeout: float = 2.0) -> None: ...

    @property
    def is_running(self) -> bool: ...

    def wait_binding_released(self, timeout: float = 1.5, poll_interval: float = 0.01) -> bool:
        """True once no binding key is held (or the listener stopped); False on timeout."""
        ...
