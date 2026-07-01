# SPDX-License-Identifier: GPL-3.0-or-later
"""Audio capture: the ``Recorder`` component (see ``spec/02-audio-capture.md``)."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from typing import Any

import numpy as np
import sounddevice

from stenographer.errors import AudioCaptureError

logger = logging.getLogger(__name__)

_FALLBACK_SAMPLE_RATES: tuple[int, ...] = (48000, 44100, 22050, 16000, 8000)


_FALLBACK_CHANNELS: tuple[int, ...] = (2, 1)


def _resample_poly(data: np.ndarray, rate_in: int, rate_out: int) -> np.ndarray:
    """Polyphase FIR resample of mono float32 audio at integer/rational rates.

    Cuts at ``min(rate_in, rate_out) / 2`` so it doubles as an anti-aliasing
    filter on downsample.  Numpy-only (no scipy dependency).  Returns a
    new ``float32`` array of shape ``(n_out,)``; returns ``data`` unchanged
    (float32 view) when ``rate_in == rate_out``.
    """
    if data.ndim != 1:
        data = np.reshape(data, -1)
    data = data.astype(np.float32, copy=False)
    if rate_in == rate_out or data.size == 0:
        return data
    gcd = math.gcd(rate_in, rate_out)
    up = rate_out // gcd
    down = rate_in // gcd
    if up == 1 and down == 1:
        return data
    n_taps = 2 * 10 * max(up, down) + 1
    half = n_taps // 2
    cutoff = 1.0 / max(up, down)
    n = np.arange(n_taps, dtype=np.float64) - half
    filt = np.sinc(cutoff * n) * cutoff * np.hanning(n_taps)
    filt *= up
    filt = filt.astype(np.float32)
    stuffed = np.zeros(data.size * up, dtype=np.float32)
    stuffed[::up] = data
    conv = np.convolve(stuffed, filt, mode="full")
    start = half
    out = conv[start::down]
    return out.astype(np.float32, copy=False)


class Recorder:
    def __init__(
        self,
        *,
        sample_rate: int,
        frames_per_buffer: int,
        device: str | int | None,
        on_error: Callable[[Exception], None],
    ) -> None:
        self._configured_rate = sample_rate
        self._sample_rate = sample_rate
        self._frames_per_buffer = frames_per_buffer
        self._device: str | int | None = None if device == "" else device
        self._on_error = on_error
        self._stream: sounddevice.InputStream | None = None
        self._buffer: bytearray | None = None
        self._overflow = False
        self._active = False
        self._channels = 1

    def start(self) -> None:
        self._buffer = bytearray()
        self._overflow = False
        rates_to_try = [self._sample_rate] + [
            r for r in _FALLBACK_SAMPLE_RATES if r != self._sample_rate
        ]
        rejected: Exception | None = None
        for channels in _FALLBACK_CHANNELS:
            for rate in rates_to_try:
                try:
                    self._stream = sounddevice.InputStream(
                        samplerate=rate,
                        channels=channels,
                        dtype="float32",
                        blocksize=self._frames_per_buffer,
                        device=self._device,
                        callback=self._on_audio,
                    )
                    self._stream.start()
                except sounddevice.PortAudioError as exc:
                    if not isinstance(exc.args, tuple) or len(exc.args) < 2:
                        raise
                    code = exc.args[1]
                    if code == -9998:
                        rejected = exc
                        break
                    if code != -9997:
                        raise
                    rejected = exc
                    logger.debug("sample rate %d Hz rejected by device; trying next fallback", rate)
                else:
                    self._active = True
                    self._channels = channels
                    if rate != self._sample_rate:
                        logger.warning(
                            "sample rate %d Hz rejected by device; fell back to %d Hz",
                            self._sample_rate,
                            rate,
                        )
                        self._sample_rate = rate
                    return
        assert rejected is not None
        raise rejected

    def _on_audio(
        self,
        indata: np.ndarray,
        frames: int,
        time: Any,
        status: sounddevice.CallbackFlags | None,
    ) -> None:
        if self._buffer is not None:
            if indata.shape[1] > 1:
                indata = indata[:, 0:1]
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
        arr = np.frombuffer(buffer, dtype=np.float32).reshape(-1, 1)
        if self._sample_rate != self._configured_rate:
            n_in = arr.shape[0]
            arr = _resample_poly(arr[:, 0], self._sample_rate, self._configured_rate).reshape(-1, 1)
            logger.info(
                "recorder: resampled captured audio from %d Hz to %d Hz (%d -> %d samples)",
                self._sample_rate,
                self._configured_rate,
                n_in,
                arr.shape[0],
            )
        return arr

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
