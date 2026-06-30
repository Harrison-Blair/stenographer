# SPDX-License-Identifier: GPL-3.0-or-later
"""Audio capture: the ``Recorder`` component (see ``spec/02-audio-capture.md``)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import numpy as np
import sounddevice

from stenographer.errors import AudioCaptureError

logger = logging.getLogger(__name__)


class Recorder:
    def __init__(
        self,
        *,
        sample_rate: int,
        frames_per_buffer: int,
        device: str | int | None,
        on_error: Callable[[Exception], None],
    ) -> None:
        self._sample_rate = sample_rate
        self._frames_per_buffer = frames_per_buffer
        self._device: str | int | None = None if device == "" else device
        self._on_error = on_error
        self._stream: sounddevice.InputStream | None = None
        self._buffer: bytearray | None = None
        self._overflow = False
        self._active = False

    def start(self) -> None:
        self._buffer = bytearray()
        self._overflow = False
        self._stream = sounddevice.InputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self._frames_per_buffer,
            device=self._device,
            callback=self._on_audio,
        )
        self._stream.start()
        self._active = True

    def _on_audio(
        self,
        indata: np.ndarray,
        frames: int,
        time: Any,
        status: sounddevice.CallbackFlags | None,
    ) -> None:
        if self._buffer is not None:
            self._buffer.extend(indata.tobytes())
        if status is not None and getattr(status, "input_overflow", False):
            self._overflow = True

    def stop(self) -> np.ndarray:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._active = False
        buffer = self._buffer
        self._buffer = None
        if self._overflow:
            self._overflow = False
            self._on_error(AudioCaptureError("input overflow during recording"))
        if not buffer:
            return np.empty((0, 1), dtype=np.float32)
        return np.frombuffer(buffer, dtype=np.float32).reshape(-1, 1)

    @property
    def is_active(self) -> bool:
        return self._active

    @staticmethod
    def default_input_device_name() -> str | None:
        try:
            info = sounddevice.query_devices(kind="input")
        except sounddevice.PortAudioError:
            return None
        return info.get("name")
