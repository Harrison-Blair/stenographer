# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path


class CuePlayer(Protocol):
    """Plays cue files; ``Feedback`` owns volume/asset policy."""

    def play(self, path: Path, volume: float) -> None: ...

    def preview(self, path: Path, volume: float) -> None:
        """Play one cue completely; a player failure raises."""
        ...
