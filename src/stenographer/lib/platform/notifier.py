# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import Protocol


class Notifier(Protocol):
    """Desktop notifications; must never raise and never block the daemon."""

    def error(self, message: str) -> None: ...

    def info(self, message: str) -> None:
        """Show *message* as a normal-urgency notice, with ``error``'s guarantees."""
        ...
