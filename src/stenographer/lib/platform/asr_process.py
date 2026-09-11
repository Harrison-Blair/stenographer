# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import Protocol


class AsrProcess(Protocol):
    """One native ASR child. The caller owns policy; this handle owns resources."""

    @property
    def pid(self) -> int | None: ...

    @property
    def exit_code(self) -> int | None: ...

    def is_running(self) -> bool: ...

    def send(self, message: tuple[object, ...]) -> None: ...

    def receive(self, timeout: float) -> object:
        """Receive one tuple message; poll expiry raises TimeoutError."""
        ...

    def close(self, graceful: bool = False) -> None:
        """Idempotently reap and release resources, draining child logs.

        Graceful close sends the existing stop tuple and grants two seconds,
        then uses the same termination/kill escalation as forced close.
        """
        ...
