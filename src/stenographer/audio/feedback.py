# SPDX-License-Identifier: GPL-3.0-or-later
"""Cue player (see ``spec/04-audio-feedback.md``)."""

from __future__ import annotations

import contextlib
import logging
import os
import pathlib
import subprocess
import threading
import time
import uuid
from typing import Literal

import soundfile

CueName = Literal[
    "ptt_on", "ptt_off", "toggle_on", "toggle_off", "error", "segment", "transcribe_done"
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
            subprocess.Popen(
                ["pw-play", f"--volume={self._volume:.2f}", str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        else:
            self._play_paplay(path)

    def _play_paplay(self, path: pathlib.Path) -> None:
        data, samplerate = soundfile.read(str(path), dtype="float32")
        scaled = data * self._volume
        xdg = os.environ.get("XDG_RUNTIME_DIR")
        if xdg:
            cue_dir = pathlib.Path(xdg) / "stenographer-cues"
        else:
            cue_dir = pathlib.Path("/tmp/stenographer-cues")
        cue_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = cue_dir / f"{uuid.uuid4()}.wav"
        soundfile.write(str(tmp_path), scaled, samplerate)
        process = subprocess.Popen(
            ["paplay", str(tmp_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        threading.Thread(
            target=self._poll_and_unlink,
            args=(process, tmp_path),
            daemon=True,
        ).start()

    @staticmethod
    def _poll_and_unlink(process: subprocess.Popen, path: pathlib.Path) -> None:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            time.sleep(0.1)
        with contextlib.suppress(FileNotFoundError):
            path.unlink()

    def close(self) -> None:
        return None
