# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from stenographer.lib.platform.linux.process import child_env, spawn_detached

if TYPE_CHECKING:
    import pathlib
    import threading

from stenographer.lib.platform.linux.cues import (
    PREVIEW_TIMEOUT_SECONDS,
    _cancellable_preview,
    build_play_command,
)


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
