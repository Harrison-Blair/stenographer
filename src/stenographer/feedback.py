# SPDX-License-Identifier: GPL-3.0-or-later
"""Cue player: four bundled WAV cues via canberra/pw-play/paplay, volume/mute."""

from __future__ import annotations

import logging
import math
import pathlib
import shutil
import subprocess
from typing import TYPE_CHECKING

from stenographer.childenv import child_env

if TYPE_CHECKING:
    from stenographer.config import FeedbackConfig

logger = logging.getLogger(__name__)

CUES: frozenset[str] = frozenset({"record_start", "record_stop", "delivered", "error"})


def build_play_command(player: str, path: pathlib.Path, volume: float) -> list[str]:
    if player == "canberra-gtk-play":
        # libcanberra accepts decibels while the config stores linear gain.
        decibels = 20.0 * math.log10(volume) if volume > 0.0 else -200.0
        return [
            "canberra-gtk-play",
            f"--file={path}",
            "--description=Stenographer cue",
            "--cache-control=volatile",
            f"--volume={decibels:.2f}",
        ]
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
    # libcanberra is purpose-built for short desktop event sounds. Prefer it to
    # pw-play, whose short-lived PipeWire streams can underrun at end-of-file.
    for player in ("canberra-gtk-play", "pw-play", "paplay"):
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
        if self._cfg.mute or self._cfg.volume <= 0.0 or self._player is None:
            return
        path = resolve_cue_path(self._asset_root, name)
        if path is None:
            return
        subprocess.Popen(
            build_play_command(self._player, path, self._cfg.volume),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=child_env(),
        )

    def close(self) -> None:
        return None
