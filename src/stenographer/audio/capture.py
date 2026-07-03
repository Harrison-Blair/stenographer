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


# Minimum real speech (seconds) accumulated since the last flush before a
# silence gap is allowed to trigger one. Guards against a click/cough followed
# by a pause flushing a near-empty segment that Whisper would hallucinate over.
_MIN_SPEECH_SECONDS: float = 0.25


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
        silence_detection: bool = False,
        silence_rms_threshold: float = 0.01,
        silence_duration_seconds: float = 1.5,
    ) -> None:
        self._configured_rate = sample_rate
        self._sample_rate = sample_rate
        self._frames_per_buffer = frames_per_buffer
        self._device: str | int | None = None if device == "" else device
        self._on_error = on_error
        self._max_seconds = max_seconds
        self._silence_detection = silence_detection
        self._silence_rms_threshold = silence_rms_threshold
        self._silence_duration_seconds = silence_duration_seconds
        self._stream: sounddevice.InputStream | None = None
        self._buffer: bytearray | None = None
        self._overflow = False
        self._capped = False
        self._active = False
        self._channels = 1
        # Silence-detection state, reset every start().
        self._on_segment: Callable[[np.ndarray], None] | None = None
        self._silent_frames = 0
        self._speech_frames = 0
        self._seen_speech = False
        self._flushed = False

    def start(self, *, on_segment: Callable[[np.ndarray], None] | None = None) -> None:
        self._buffer = bytearray()
        self._overflow = False
        self._capped = False
        self._on_segment = on_segment
        self._silent_frames = 0
        self._speech_frames = 0
        self._seen_speech = False
        self._flushed = False
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
            max_bytes = self._max_seconds * self._sample_rate * 4
            if self._capped:
                pass
            elif 0 < max_bytes <= len(self._buffer):
                # Cap the buffer (mono float32: 4 bytes/sample). Recording
                # keeps running until the user stops it; the transcript
                # covers the first max_seconds only.
                self._capped = True
                self._on_error(
                    AudioCaptureError(
                        f"recording exceeded {self._max_seconds}s; capture truncated"
                    )
                )
            else:
                if indata.shape[1] > 1:
                    indata = indata[:, 0:1]
                self._buffer.extend(indata.tobytes())
                if self._silence_detection and self._on_segment is not None:
                    self._detect_silence(indata[:, 0], frames)
        if status is not None and getattr(status, "input_overflow", False):
            self._overflow = True

    def _detect_silence(self, mono: np.ndarray, frames: int) -> None:
        """Track speech/silence energy and flush a segment on a long pause.

        Runs on the PortAudio thread, so it is serialized with the buffer
        appends in ``_on_audio``; no lock is needed. A flush only fires after a
        run of trailing silence, so any brief CPU spike (e.g. resampling a
        fallback-rate segment) lands on quiet audio rather than dropping speech.
        """
        if frames <= 0:
            return
        rms = float(np.sqrt(np.mean(np.square(mono))))
        if rms >= self._silence_rms_threshold:
            self._silent_frames = 0
            self._speech_frames += frames
            if self._speech_frames >= _MIN_SPEECH_SECONDS * self._sample_rate:
                self._seen_speech = True
            return
        self._silent_frames += frames
        if not self._seen_speech:
            return
        if self._silent_frames < self._silence_duration_seconds * self._sample_rate:
            return
        arr = self._finalize(self._buffer, log_resample=False)
        self._buffer = bytearray()
        self._silent_frames = 0
        self._speech_frames = 0
        self._seen_speech = False
        self._flushed = True
        if arr.shape[0] > 0 and self._on_segment is not None:
            self._on_segment(arr)

    def _finalize(self, buffer: bytearray | None, *, log_resample: bool = True) -> np.ndarray:
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
        if self._silence_detection and self._flushed and self._speech_frames == 0:
            # Everything since the last flush is silence; return nothing so the
            # session does not transcribe an empty tail (and play the error cue)
            # right after a flush.
            return np.empty((0, 1), dtype=np.float32)
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
