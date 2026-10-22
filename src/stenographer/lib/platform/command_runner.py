# SPDX-License-Identifier: GPL-3.0-or-later
"""Contract for running a host command to completion, used by explicit model builds."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class CommandRunner(Protocol):
    """Run a command without a shell and return its exit code (127 when it cannot start)."""

    def run(self, argv: Sequence[str]) -> int:
        """Run with inherited stdout and stderr, so the user sees progress."""
        ...

    def run_quiet(self, argv: Sequence[str]) -> int:
        """Run with stdout and stderr discarded."""
        ...
