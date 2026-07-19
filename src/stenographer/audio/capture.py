# SPDX-License-Identifier: GPL-3.0-or-later
"""Audio capture: the ``Recorder`` component."""

from __future__ import annotations

import logging
import math
import threading
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

    True polyphase: the filter is decomposed into ``up`` sub-filters and
    each output sample is drawn from one short convolution of the input,
    so the ``data.size * up`` zero-stuffed intermediate (gigabytes for a
    44.1 kHz -> 16 kHz capture, where ``up == 160``) is never built.
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
    # Output m taps the virtual full convolution at n = half + m*down:
    #   y[m] = sum_k data[k] * filt[n - k*up]
    # Grouping by p = n % up, each group is a plain convolution of the
    # input with the sub-filter filt[p::up], sampled at q = n // up.
    total = data.size * up + n_taps - 1
    ms = np.arange((total - half + down - 1) // down)
    ns = half + ms * down
    ps = ns % up
    qs = ns // up
    out = np.zeros(ms.size, dtype=np.float32)
    for p in np.unique(ps):
        sel = ps == p
        conv_p = np.convolve(data, filt[p::up], mode="full")
        q_sel = qs[sel]
        valid = q_sel < conv_p.size
        vals = np.zeros(q_sel.size, dtype=np.float32)
        vals[valid] = conv_p[q_sel[valid]]
        out[sel] = vals
    return out


class Recorder:
    def __init__(
        self,
        *,
        sample_rate: int,
        frames_per_buffer: int,
        device: str | int | None,
        on_error: Callable[[Exception], None],
        max_seconds: int = 0,
        on_audio: Callable[[np.ndarray, int], None] | None = None,
        max_audio_observer_interval_seconds: float | None = None,
    ) -> None:
        self._configured_rate = sample_rate
        self._sample_rate = sample_rate
        self._frames_per_buffer = frames_per_buffer
        self._device: str | int | None = None if device == "" else device
        self._on_error = on_error
        self._max_seconds = max_seconds
        self._on_audio_block = on_audio
        self._max_audio_observer_interval_seconds = max_audio_observer_interval_seconds
        self._stream: sounddevice.InputStream | None = None
        self._buffer: bytearray | None = None
        # Guards _buffer appends/reads shared between the PortAudio callback
        # and snapshot() on the incremental driver thread. Held only around the
        # extend/copy themselves, so the callback stays effectively
        # non-blocking.
        self._buffer_lock = threading.Lock()
        self._overflow = False
        self._capped = False
        self._active = False
        self._channels = 1
        # Incremental-decode partial signal, reset every start().
        self._on_partial: Callable[[], None] | None = None
        self._min_partial_seconds = 1.0
        self._partial_frames = 0

    def start(
        self,
        *,
        on_partial: Callable[[], None] | None = None,
        min_partial_seconds: float = 1.0,
    ) -> None:
        """Open the input stream.

        *on_partial* (the incremental-decode signal) fires on the PortAudio
        thread every *min_partial_seconds* of newly captured audio and must
        only enqueue a signal and return.
        """
        self._buffer = bytearray()
        self._overflow = False
        self._capped = False
        self._on_partial = on_partial
        self._min_partial_seconds = min_partial_seconds
        self._partial_frames = 0
        rates_to_try = [self._sample_rate] + [
            r for r in _FALLBACK_SAMPLE_RATES if r != self._sample_rate
        ]
        rejected: Exception | None = None
        for channels in _FALLBACK_CHANNELS:
            for rate in rates_to_try:
                try:
                    blocksize = self._frames_per_buffer
                    if (
                        self._on_audio_block is not None
                        and self._max_audio_observer_interval_seconds is not None
                    ):
                        observer_blocksize = max(
                            64,
                            int(rate * self._max_audio_observer_interval_seconds),
                        )
                        blocksize = min(blocksize, observer_blocksize)
                    self._stream = sounddevice.InputStream(
                        samplerate=rate,
                        channels=channels,
                        dtype="float32",
                        blocksize=blocksize,
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
            max_bytes = self._max_seconds * self._sample_rate * 4
            if self._capped:
                pass
            elif 0 < max_bytes <= len(self._buffer):
                # Cap the buffer (mono float32: 4 bytes/sample). Recording
                # keeps running until the user stops it; the transcript
                # covers the first max_seconds only.
                self._capped = True
                self._on_error(
                    AudioCaptureError(f"recording exceeded {self._max_seconds}s; capture truncated")
                )
            else:
                if indata.shape[1] > 1:
                    indata = indata[:, 0:1]
                with self._buffer_lock:
                    self._buffer.extend(indata.tobytes())
                if self._on_audio_block is not None:
                    try:
                        self._on_audio_block(indata[:, 0], self._sample_rate)
                    except Exception as exc:
                        # Visual feedback is optional and must never interrupt
                        # PortAudio's real-time callback.
                        logger.debug("recorder: audio observer failed: %s", exc)
                if self._on_partial is not None:
                    self._partial_frames += frames
                    if self._partial_frames >= self._min_partial_seconds * self._sample_rate:
                        self._partial_frames = 0
                        self._on_partial()
        if status is not None and getattr(status, "input_overflow", False):
            self._overflow = True

    def _finalize(
        self, buffer: bytearray | bytes | None, *, log_resample: bool = True
    ) -> np.ndarray:
        """Convert a raw capture buffer to a mono ``(N, 1)`` float32 array,
        resampling from the actual device rate to the configured rate if the
        device fell back to a different rate. Shared by ``stop()`` and the
        mid-recording flush path."""
        if not buffer:
            return np.empty((0, 1), dtype=np.float32)
        arr = np.frombuffer(buffer, dtype=np.float32).reshape(-1, 1)
        if self._sample_rate != self._configured_rate:
            n_in = arr.shape[0]
            arr = _resample_poly(arr[:, 0], self._sample_rate, self._configured_rate).reshape(-1, 1)
            if log_resample:
                logger.info(
                    "recorder: resampled captured audio from %d Hz to %d Hz (%d -> %d samples)",
                    self._sample_rate,
                    self._configured_rate,
                    n_in,
                    arr.shape[0],
                )
        return arr

    def snapshot(self, start_seconds: float = 0.0) -> np.ndarray:
        """Copy the captured audio from *start_seconds* (configured-rate
        seconds) to now, as a mono ``(N, 1)`` float32 array at the configured
        rate.

        Called from the incremental driver thread while the PortAudio callback
        is still appending. The raw device-rate buffer is sliced under the
        lock (cost proportional to the window, not the recording) and
        resampled outside it. Second-based slicing keeps the boundary
        rate-agnostic when the device fell back to another rate.
        """
        offset = round(start_seconds * self._sample_rate) * 4
        with self._buffer_lock:
            if self._buffer is None or offset >= len(self._buffer):
                return np.empty((0, 1), dtype=np.float32)
            window = bytes(self._buffer[offset:])
        return self._finalize(window, log_resample=False)

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
        return self._finalize(buffer)

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
