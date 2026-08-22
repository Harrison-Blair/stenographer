# SPDX-License-Identifier: GPL-3.0-or-later
"""Cue playback via canberra-gtk-play / pw-play / paplay (the Linux ``CuePlayer``).

``build_play_command`` is the pure unit target; ``LinuxCuePlayer.play`` only
spawns the chosen player — mute, volume, and asset policy stay in
``stenographer.delivery.feedback.Feedback``.
"""

from __future__ import annotations

import math
import shutil
import subprocess
from typing import TYPE_CHECKING

from stenographer.platform.linux.process import child_env

if TYPE_CHECKING:
    import pathlib


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


def detect_player() -> str | None:
    # libcanberra is purpose-built for short desktop event sounds. Prefer it to
    # pw-play, whose short-lived PipeWire streams can underrun at end-of-file.
    for player in ("canberra-gtk-play", "pw-play", "paplay"):
        if shutil.which(player):
            return player
    return None


class LinuxCuePlayer:
    """Spawns the detected command-line player, detached and non-blocking."""

    def __init__(self, player: str) -> None:
        self._player = player

    def play(self, path: pathlib.Path, volume: float) -> None:
        subprocess.Popen(
            build_play_command(self._player, path, volume),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=child_env(),
        )
