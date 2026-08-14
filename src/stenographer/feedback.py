# SPDX-License-Identifier: GPL-3.0-or-later
"""Cue player: five bundled WAV cues via pw-play/paplay, global volume/mute."""

from __future__ import annotations

import logging
import pathlib
import shutil
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stenographer.config import FeedbackConfig

logger = logging.getLogger(__name__)

CUES: frozenset[str] = frozenset(
    {"record_start", "record_stop", "delivered", "error", "model_loading"}
)


def build_play_command(player: str, path: pathlib.Path, volume: float) -> list[str]:
    if player == "pw-play":
        return ["pw-play", f"--volume={volume:.2f}", str(path)]
    # paplay volume is linear 0..65536.
    return ["paplay", f"--volume={int(volume * 65536)}", str(path)]


def resolve_cue_path(asset_root: pathlib.Path, name: str) -> pathlib.Path | None:
    path = asset_root / f"{name}.wav"
    if path.is_file():
        return path
    logger.warning("cue %r: no asset found; skipping", name)
    return None


def detect_player() -> str | None:
    for player in ("pw-play", "paplay"):
        if shutil.which(player):
            return player
    return None


class Feedback:
    def __init__(
        self,
        *,
        cfg: FeedbackConfig,
        player: str | None = None,
        asset_root: pathlib.Path | None = None,
    ) -> None:
        self._cfg = cfg
        self._player = player if player is not None else detect_player()
        self._asset_root = (
            asset_root
            if asset_root is not None
            else pathlib.Path(__file__).parent / "assets" / "sounds"
        )

    def play(self, name: str) -> None:
        if self._cfg.mute or self._player is None:
            return
        path = resolve_cue_path(self._asset_root, name)
        if path is None:
            return
        subprocess.Popen(
            build_play_command(self._player, path, self._cfg.volume),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def close(self) -> None:
        return None
