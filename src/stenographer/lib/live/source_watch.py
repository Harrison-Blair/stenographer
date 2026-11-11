# SPDX-License-Identifier: GPL-3.0-or-later
"""Find live sources that stopped delivering audio. PURE: the caller passes the time."""

from __future__ import annotations

SILENT_SECONDS = 5.0
_ORDER = ("mic", "system")


class SourceWatch:
    """The time of the last block of each running source.

    A source that delivered no block for ``SILENT_SECONDS`` is silent. Nothing
    restarts it; the session only reports it until a block arrives.
    """

    def __init__(self) -> None:
        self._last_block: dict[str, float] = {}
        self._warned: set[str] = set()

    def started(self, source: str, now: float) -> None:
        self._last_block[source] = now

    def block(self, source: str, now: float) -> None:
        if source in self._last_block:
            self._last_block[source] = now

    def stopped(self, source: str) -> None:
        self._last_block.pop(source, None)
        self._warned.discard(source)

    def silent(self, now: float) -> tuple[str, ...]:
        return tuple(
            source
            for source in _ORDER
            if source in self._last_block and now - self._last_block[source] >= SILENT_SECONDS
        )

    def check(self, now: float) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Return the sources that became silent and the sources that delivered again."""
        silent = self.silent(now)
        became_silent = tuple(source for source in silent if source not in self._warned)
        resumed = tuple(source for source in _ORDER if source in self._warned - set(silent))
        self._warned = set(silent)
        return became_silent, resumed
