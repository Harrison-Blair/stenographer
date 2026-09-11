# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import Protocol


class HelperProcess(Protocol):
    """One live overlay-helper child process, with its two pipes.

    The supervisor owns every policy above this line (mailbox, NDJSON framing,
    readiness deadline, restart budget); the host owns pipe creation, the
    blocking wait for helper output, and process termination — none of which
    survives a move between OSes unchanged (``selectors.SelectSelector``
    accepts only sockets on Windows; POSIX signal escalation has no analogue
    there).
    """

    def write(self, data: bytes) -> None:
        """Write *data* to the helper's stdin and flush; raises ``OSError``."""
        ...

    def close_input(self) -> None:
        """Close the helper's stdin so it sees EOF. Never raises."""
        ...

    def wait_readable(self, timeout: float) -> bool:
        """Block up to *timeout* seconds; ``True`` when stdout has bytes or EOF."""
        ...

    def read(self, size: int) -> bytes:
        """Read at most *size* bytes; ``b""`` at EOF *and* on any read error."""
        ...

    def is_running(self) -> bool:
        """``True`` while the child has not exited (no blocking, no reaping)."""
        ...

    def wait(self, timeout: float) -> None:
        """Wait up to *timeout* seconds for a voluntary exit. Never raises."""
        ...

    def terminate(self, grace_seconds: float) -> None:
        """Stop the child with the host's escalation, then reap it. Never raises.

        Called after the supervisor has already granted an expected exit its
        own grace period, so an implementation escalates immediately; *grace*
        bounds each step of that escalation.
        """
        ...

    def close(self) -> None:
        """Release the pipes and any polling resources. Never raises."""
        ...
