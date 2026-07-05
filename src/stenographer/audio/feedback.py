# SPDX-License-Identifier: GPL-3.0-or-later
"""Cue player (see ``spec/04-audio-feedback.md``)."""

from __future__ import annotations

import logging
import pathlib
import subprocess
from typing import Literal

CueName = Literal[
    "ptt_on",
    "ptt_off",
    "toggle_on",
    "toggle_off",
    "cancel",
    "discard",
    "error",
    "segment",
    "transcribe_done",
    "model_loading",
    "model_ready",
]

logger = logging.getLogger(__name__)


class Feedback:
    def __init__(
        self,
        *,
        player: Literal["pw-play", "paplay"] | None,
        asset_root: pathlib.Path,
        override_root: dict[CueName, pathlib.Path],
        volume: float,
        muted: bool,
    ) -> None:
        self._player = player
        self._asset_root = asset_root
        self._override_root = dict(override_root)
        self._volume = volume
        self._muted = muted

    def _resolve_path(self, name: CueName) -> pathlib.Path | None:
        override = self._override_root.get(name)
        if override is not None and override.is_file():
            return override
        bundled = self._asset_root / f"{name}.wav"
        if bundled.is_file():
            return bundled
        logger.warning("cue %r: no asset found; skipping", name)
        return None

    def play(self, name: CueName) -> None:
        if self._muted or self._player is None:
            return
        path = self._resolve_path(name)
        if path is None:
            logger.warning("cue %r: no asset found; skipping", name)
            return
        if self._player == "pw-play":
            cmd = ["pw-play", f"--volume={self._volume:.2f}", str(path)]
        else:
            # paplay volume is linear 0..65536.
            cmd = ["paplay", f"--volume={int(self._volume * 65536)}", str(path)]
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def close(self) -> None:
        return None
