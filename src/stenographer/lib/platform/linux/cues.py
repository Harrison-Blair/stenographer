# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import math
import shutil
import subprocess
import time
from typing import TYPE_CHECKING

from stenographer.lib.platform.linux.process import child_env

if TYPE_CHECKING:
    import pathlib
    import threading

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
