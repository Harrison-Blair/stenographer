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
import time
from typing import TYPE_CHECKING

from stenographer.platform.linux.process import child_env, spawn_detached

if TYPE_CHECKING:
    import pathlib
    import threading

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
        spawn_detached(build_play_command(self._player, path, volume))

    def preview(
        self, path: pathlib.Path, volume: float, *, cancellation: threading.Event | None = None
    ) -> None:
        """Play one preview cue completely so command failure is observable.

        Waits at most ``PREVIEW_TIMEOUT_SECONDS``; ``subprocess.TimeoutExpired``
        propagates so callers can report a stalled player.
        """

        if cancellation is not None:
            _cancellable_preview(build_play_command(self._player, path, volume), cancellation)
            return
        subprocess.run(
            build_play_command(self._player, path, volume),
            check=True,
            timeout=PREVIEW_TIMEOUT_SECONDS,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=child_env(),
        )


def _cancellable_preview(command: list[str], cancellation: threading.Event) -> None:
    """Stop and reap an actual player process as soon as its lease is cancelled."""
    if cancellation.is_set():
        raise RuntimeError("Sound preview cancelled")
    with subprocess.Popen(
        command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=child_env()
    ) as process:
        deadline = time.monotonic() + PREVIEW_TIMEOUT_SECONDS
        try:
            while process.poll() is None:
                if cancellation.wait(0.02):
                    raise RuntimeError("Sound preview cancelled")
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(command, PREVIEW_TIMEOUT_SECONDS)
            if cancellation.is_set():
                raise RuntimeError("Sound preview cancelled")
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, command)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
