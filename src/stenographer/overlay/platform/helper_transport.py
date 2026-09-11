# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from stenographer.overlay.platform.helper_process import HelperProcess


class HelperTransport(Protocol):
    """Spawns overlay helper processes with the pipe layout the supervisor needs."""

    def spawn(self, command: Sequence[str], *, stderr_path: Path | None = None) -> HelperProcess:
        """Start *command*; raises ``OSError``/``ValueError`` when it cannot start.

        *stderr_path* is the file the child's stderr appends to, so a display
        library's own chatter is captured beside the helper's records instead of
        filling a pipe nobody drains. ``None`` discards it.
        """
        ...
