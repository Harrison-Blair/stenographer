# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import threading
    from pathlib import Path


class CuePlayer(Protocol):
    """Plays cue files; ``Feedback`` owns mute/volume/asset policy."""

    def play(self, path: Path, volume: float) -> None: ...

    def preview(
        self, path: Path, volume: float, *, cancellation: threading.Event | None = None
    ) -> None:
        """Play one cue; cancellation stops native playback and raises."""
        ...
