# SPDX-License-Identifier: GPL-3.0-or-later
"""Cue policy: four bundled WAV cues, volume/mute, played through a platform ``CuePlayer``."""

from __future__ import annotations

import logging
import pathlib
from importlib.resources import files
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stenographer.config import FeedbackConfig
    from stenographer.platform.base import CuePlayer

logger = logging.getLogger(__name__)

CUES: frozenset[str] = frozenset({"record_start", "record_stop", "delivered", "error"})


def resolve_cue_path(asset_root: pathlib.Path, name: str) -> pathlib.Path | None:
    path = asset_root / f"{name}.wav"
    if path.is_file():
        return path
    logger.warning("cue %r: no asset found; skipping", name)
    return None


class Feedback:
    """Owns mute/volume/asset policy; ``player`` (``None`` = no cues) only spawns."""

    def __init__(
        self,
        *,
        cfg: FeedbackConfig,
        player: CuePlayer | None,
        asset_root: pathlib.Path | None = None,
    ) -> None:
        self._cfg = cfg
        self._player = player
        self._asset_root = (
            asset_root
            if asset_root is not None
            else pathlib.Path(str(files("stenographer"))) / "assets" / "sounds"
        )

    def play(self, name: str) -> None:
        if self._cfg.mute or self._cfg.volume <= 0.0 or self._player is None:
            return
        path = resolve_cue_path(self._asset_root, name)
        if path is None:
            return
        self._player.play(path, self._cfg.volume)

    def close(self) -> None:
        return None
