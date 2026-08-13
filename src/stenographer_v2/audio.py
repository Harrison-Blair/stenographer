# SPDX-License-Identifier: GPL-3.0-or-later
"""Audio capture: the ``Recorder`` and the pure energy gate.

The PortAudio callback only copies each block (§4.8). ``sounddevice`` is
imported lazily inside ``Recorder.start`` so the pure helpers (the RMS gate and
the resampler) import without PortAudio present. Sample-rate and channel
fallback (§4.9) polyphase-resample the capture to the fixed ASR rate.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

_SAMPLE_RATE = 16000
_GATE_FRAME_SECONDS = 0.050
_FALLBACK_SAMPLE_RATES: tuple[int, ...] = (48000, 44100, 22050, 16000, 8000)
_FALLBACK_CHANNELS: tuple[int, ...] = (2, 1)
_ERR_BAD_CHANNELS = -9998
_ERR_BAD_SAMPLE_RATE = -9997


def speech_gate_passes(samples: np.ndarray, sample_rate: int, min_rms: float) -> bool:
    """True if the capture clears the pre-decode energy gate (§4.1).

    Disabled (always True) when *min_rms* <= 0. Otherwise the capture passes
    only when two consecutive 50 ms frames both exceed the RMS threshold, so
    isolated clicks and dead air are rejected without eating soft speech
    onsets — the quiet-mic case the owner's setup depends on.
    """
    if min_rms <= 0:
        return True
    audio = np.asarray(samples, dtype=np.float32).reshape(-1)
    frame = max(1, int(sample_rate * _GATE_FRAME_SECONDS))
    n_frames = audio.size // frame
    if n_frames < 2:
        return False
    trimmed = audio[: n_frames * frame].reshape(n_frames, frame)
    rms = np.sqrt(np.mean(trimmed * trimmed, axis=1))
    loud = rms > min_rms
    return bool(np.any(loud[:-1] & loud[1:]))


def _resample_poly(data: np.ndarray, rate_in: int, rate_out: int) -> np.ndarray:
    """Polyphase FIR resample of mono float32 audio at rational rates.

    Cuts at ``min(rate_in, rate_out) / 2`` so it doubles as an anti-aliasing
    filter on downsample. Numpy-only. Returns ``data`` unchanged (as float32)
    when the rates match.
    """
    data = np.asarray(data, dtype=np.float32).reshape(-1)
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
    filt = (filt * up).astype(np.float32)
    # Output m taps the virtual full convolution at n = half + m*down; grouping
    # by p = n % up turns each group into a plain convolution with sub-filter
    # filt[p::up], sampled at q = n // up, so no zero-stuffed array is built.
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
    """Captures mono float32 audio at the fixed ASR rate.

    ``start`` opens the input stream, negotiating channels and sample rate down
    the fallback lists; ``stop`` returns the whole capture as a 1-D float32
    array, resampled to the ASR rate if the device fell back.
    """

    def __init__(self, *, device: str | int | None, max_seconds: int) -> None:
        self._device: str | int | None = None if device == "" else device
        self._max_seconds = max_seconds
        self._stream: Any = None
        self._device_rate = _SAMPLE_RATE
        self._blocks: list[np.ndarray] = []
        self._frames = 0
        self._max_frames = 0
        self._capped = False
        self._overflow = False
        self._active = False

    def start(self) -> None:
        import sounddevice

        self._blocks = []
        self._frames = 0
        self._capped = False
        self._overflow = False
        rates = [_SAMPLE_RATE, *(r for r in _FALLBACK_SAMPLE_RATES if r != _SAMPLE_RATE)]
        rejected: Exception | None = None
        for channels in _FALLBACK_CHANNELS:
            for rate in rates:
                try:
                    stream = sounddevice.InputStream(
                        samplerate=rate,
                        channels=channels,
                        dtype="float32",
                        device=self._device,
                        callback=self._on_audio,
                    )
                    stream.start()
                except sounddevice.PortAudioError as exc:
                    has_code = isinstance(exc.args, tuple) and len(exc.args) >= 2
                    code = exc.args[1] if has_code else None
                    if code == _ERR_BAD_CHANNELS:
                        rejected = exc
                        break
                    if code != _ERR_BAD_SAMPLE_RATE:
                        raise
                    rejected = exc
                else:
                    self._stream = stream
                    self._device_rate = rate
                    self._max_frames = self._max_seconds * rate
                    self._active = True
                    if rate != _SAMPLE_RATE:
                        logger.warning(
                            "recorder: device rejected %d Hz; using %d Hz", _SAMPLE_RATE, rate
                        )
                    return
        assert rejected is not None
        raise rejected

    def _on_audio(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        if status is not None and getattr(status, "input_overflow", False):
            self._overflow = True
        if self._capped:
            return
        block = indata[:, 0].copy() if indata.ndim == 2 else indata.copy()
        self._blocks.append(block)
        self._frames += block.shape[0]
        if self._max_frames and self._frames >= self._max_frames:
            self._capped = True

    def stop(self) -> np.ndarray:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._active = False
        if self._overflow:
            logger.warning("recorder: input overflow during capture")
        if self._capped:
            logger.warning("recorder: capture reached %ds cap; audio truncated", self._max_seconds)
        if not self._blocks:
            return np.empty(0, dtype=np.float32)
        audio = np.concatenate(self._blocks)
        self._blocks = []
        if self._device_rate != _SAMPLE_RATE:
            audio = _resample_poly(audio, self._device_rate, _SAMPLE_RATE)
        return audio.astype(np.float32, copy=False)

    @property
    def is_active(self) -> bool:
        return self._active
