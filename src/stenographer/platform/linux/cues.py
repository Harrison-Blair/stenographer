# SPDX-License-Identifier: GPL-3.0-or-later
"""Cue playback via canberra-gtk-play / pw-play / paplay (the Linux ``CuePlayer``).

``build_play_command`` is the pure unit target. Runtime cues are spawned
non-blocking; explicit previews wait (bounded by ``PREVIEW_TIMEOUT_SECONDS``)
and report player failure or a stalled player. Mute, volume, and asset policy
stay in ``stenographer.delivery.feedback.Feedback``.
"""

from __future__ import annotations

import math
import shutil
import subprocess
from typing import TYPE_CHECKING

from stenographer.platform.linux.process import child_env

if TYPE_CHECKING:
    import pathlib

# Cues are at most ~0.3 s long; a preview that has not finished in ten seconds
# means the player is stalled, not still playing.
PREVIEW_TIMEOUT_SECONDS = 10.0


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
    """Runs the detected player asynchronously for cues and synchronously for previews."""

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

    def preview(self, path: pathlib.Path, volume: float) -> None:
        """Play one preview cue completely so command failure is observable.

        Waits at most ``PREVIEW_TIMEOUT_SECONDS``; ``subprocess.TimeoutExpired``
        propagates so callers can report a stalled player.
        """

        subprocess.run(
            build_play_command(self._player, path, volume),
            check=True,
            timeout=PREVIEW_TIMEOUT_SECONDS,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=child_env(),
        )
