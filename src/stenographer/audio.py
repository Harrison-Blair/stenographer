# SPDX-License-Identifier: GPL-3.0-or-later
"""Audio capture: the ``Recorder`` and the pure energy gate.

The PortAudio callback only copies each block — never analysis. ``sounddevice``
is imported lazily inside ``Recorder.prepare`` so the pure helpers (the RMS gate
and the resampler) import without PortAudio present. Sample-rate and channel
fallback polyphase-resample the capture to the fixed ASR rate.
"""

from __future__ import annotations

import contextlib
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

import numpy as np

from stenographer.constants import SAMPLE_RATE
from stenographer.utils.logging_setup import fmt_event, log_failure

logger = logging.getLogger(__name__)

_GATE_FRAME_SECONDS = 0.050
_FALLBACK_SAMPLE_RATES: tuple[int, ...] = (48000, 44100, 22050, 16000, 8000)
_FALLBACK_CHANNELS: tuple[int, ...] = (2, 1)
_ERR_BAD_CHANNELS = -9998
_ERR_BAD_SAMPLE_RATE = -9997


class RecorderState(Enum):
    """PortAudio lifecycle state for :class:`Recorder`."""

    UNPREPARED = auto()
    PREPARED = auto()
    CAPTURING = auto()


@dataclass(frozen=True)
class GateStats:
    """The energy gate's verdict and the numbers it was reached from."""

    peak_rms: float
    mean_rms: float
    frames_total: int
    frames_above: int
    threshold: float
    passed: bool


@dataclass(frozen=True)
class CaptureStats:
    """What one completed capture cost, for the utterance summary line.

    Rate and channel count are deliberately absent: they are properties of the
    negotiated stream, not of one capture, and ``recorder: prepared`` already
    reports them once per negotiation.
    """

    activate_ms: float
    capture_seconds: float
    input_frames: int
    output_frames: int
    overflow: bool
    capped: bool


def speech_gate_stats(samples: np.ndarray, sample_rate: int, min_rms: float) -> GateStats:
    """Frame the capture once and return both the verdict and its numbers. PURE.

    The verdict and the reported energy come from a single computation on
    purpose: a log line whose numbers were measured separately from the
    decision it explains can disagree with it, and a quiet-mic false reject is
    exactly the case that has to be diagnosable from the log alone.

    Disabled (always passing) when *min_rms* <= 0. Otherwise the capture passes
    only when two consecutive 50 ms frames both exceed the RMS threshold, so
    isolated clicks and dead air are rejected without eating soft speech
    onsets — the quiet-mic case the owner's setup depends on.
    """
    audio = np.asarray(samples, dtype=np.float32).reshape(-1)
    frame = max(1, int(sample_rate * _GATE_FRAME_SECONDS))
    n_frames = audio.size // frame
    if n_frames == 0:
        return GateStats(0.0, 0.0, 0, 0, min_rms, min_rms <= 0)
    trimmed = audio[: n_frames * frame].reshape(n_frames, frame)
    rms = np.sqrt(np.mean(trimmed * trimmed, axis=1))
    loud = rms > min_rms
    passed = min_rms <= 0 or (n_frames >= 2 and bool(np.any(loud[:-1] & loud[1:])))
    return GateStats(
        peak_rms=float(rms.max()),
        mean_rms=float(rms.mean()),
        frames_total=n_frames,
        frames_above=int(np.count_nonzero(loud)),
        threshold=min_rms,
        passed=passed,
    )


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

    ``prepare`` opens (but does not start) an input stream, negotiating channels
    and sample rate down the fallback lists. ``start`` activates that retained
    stream and ``stop`` returns it to the prepared/stopped state for the next
    capture. Audio is returned as a 1-D float32 array at the ASR rate.
    """

    def __init__(
        self,
        *,
        device: str | int | None,
        max_seconds: int,
        on_block: Callable[[np.ndarray, int, int], None] | None = None,
    ) -> None:
        normalized_device: str | int | None = None if device == "" else device
        if isinstance(normalized_device, str) and normalized_device.isdecimal():
            normalized_device = int(normalized_device)
        self._configured_device = normalized_device
        self._selected_device: str | int | None = self._configured_device
        self._max_seconds = max_seconds
        self._on_block = on_block
        self._stream: Any = None
        self._stream_epoch = 0
        self._device_rate = SAMPLE_RATE
        self._channels = 1
        self._blocks: list[np.ndarray] = []
        self._frames = 0
        self._max_frames = 0
        self._capped = False
        self._overflow = False
        self._capture_started_at: float | None = None
        self._activation_ms = 0.0
        # One utterance at a time (a daemon invariant), so the last completed
        # capture is unambiguously the one the pipeline thread is about to run.
        self._last_capture: CaptureStats | None = None
        self._state = RecorderState.UNPREPARED

    def prepare(self) -> None:
        """Negotiate and retain a stopped stream without starting callbacks.

        Repeated calls while prepared or capturing are no-ops. A failed
        negotiation leaves the recorder unprepared so the next press can try
        the then-current default input device.
        """
        if self._state is not RecorderState.UNPREPARED:
            return
        import sounddevice

        started_at = time.perf_counter()
        try:
            self._select_default_device(sounddevice)
            self._negotiate(sounddevice)
        except Exception:
            self._invalidate(reselect_default=True)
            raise
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        logger.info(
            "recorder: prepared duration_ms=%.1f rate_hz=%d channels=%d",
            elapsed_ms,
            self._device_rate,
            self._channels,
        )

    def _select_default_device(self, sounddevice: Any) -> None:
        if self._configured_device is not None or self._selected_device is not None:
            return
        device = sounddevice.query_devices(kind="input")
        self._selected_device = int(device["index"])

    def _negotiate(self, sounddevice: Any) -> None:
        rates = [SAMPLE_RATE, *(r for r in _FALLBACK_SAMPLE_RATES if r != SAMPLE_RATE)]
        rejected: Exception | None = None
        for channels in _FALLBACK_CHANNELS:
            for rate in rates:
                try:
                    stream = sounddevice.InputStream(
                        samplerate=rate,
                        channels=channels,
                        dtype="float32",
                        device=self._selected_device,
                        callback=self._on_audio,
                    )
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
                    self._stream_epoch += 1
                    self._device_rate = rate
                    self._channels = channels
                    self._max_frames = self._max_seconds * rate
                    self._state = RecorderState.PREPARED
                    if rate != SAMPLE_RATE:
                        logger.warning(
                            "recorder: fallback rate_hz=%d requested_rate_hz=%d",
                            rate,
                            SAMPLE_RATE,
                        )
                    return
        assert rejected is not None
        raise rejected

    def start(self) -> None:
        """Start capture, recovering once when a retained stream has gone stale.

        An unprepared recorder gets one normal negotiate-and-start attempt. If
        a stream retained from startup or a previous capture fails to activate,
        it is discarded and exactly one fresh negotiate-and-start is attempted.
        """
        if self._state is RecorderState.CAPTURING:
            raise RuntimeError("recorder is already capturing")
        retained = self._state is RecorderState.PREPARED
        if not retained:
            self.prepare()
        self._blocks = []
        self._frames = 0
        self._capped = False
        self._overflow = False
        try:
            self._activate(recovery="none")
        except Exception as exc:
            log_failure(
                logger,
                logging.WARNING,
                "recorder: activation_failed",
                exc,
                safe=True,
                retained=int(retained),
            )
            self._invalidate(reselect_default=True)
            if not retained:
                raise
            try:
                self.prepare()
                self._activate(recovery="renegotiated")
            except Exception as retry_exc:
                log_failure(
                    logger,
                    logging.WARNING,
                    "recorder: recovery_failed",
                    retry_exc,
                    safe=True,
                    phase="activate",
                )
                self._invalidate(reselect_default=True)
                raise

    def _activate(self, *, recovery: str) -> None:
        if self._stream is None or self._state is not RecorderState.PREPARED:
            raise RuntimeError("recorder has no prepared stream")
        started_at = time.perf_counter()
        self._stream.start()
        activation_ms = (time.perf_counter() - started_at) * 1000.0
        self._capture_started_at = time.perf_counter()
        self._activation_ms = activation_ms
        self._last_capture = None
        self._state = RecorderState.CAPTURING
        # DEBUG, not INFO: this runs under the daemon's state lock, and the
        # numbers reach the log through the utterance summary line instead.
        logger.debug(
            fmt_event(
                "recorder",
                "activated",
                duration_ms=round(activation_ms, 1),
                rate_hz=self._device_rate,
                channels=self._channels,
                recovery=recovery,
            )
        )

    def _on_audio(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        if status is not None and getattr(status, "input_overflow", False):
            self._overflow = True
        if self._capped:
            return
        block = indata[:, 0].copy() if indata.ndim == 2 else indata.copy()
        self._blocks.append(block)
        if self._on_block is not None:
            # The block is already the callback's required mono copy.  The
            # optional sink may only replace a latest-only in-memory slot.
            with contextlib.suppress(Exception):
                self._on_block(block, self._device_rate, self._stream_epoch)
        self._frames += block.shape[0]
        if self._max_frames and self._frames >= self._max_frames:
            self._capped = True

    def stop(self) -> np.ndarray:
        """Stop capture, secure the samples, and retain the stopped stream.

        Any stream/stop or sample-finalization failure invalidates the stream
        and discards the whole uncertain capture. Calling ``stop`` while merely
        prepared is harmless and returns an empty array.
        """
        if self._state is not RecorderState.CAPTURING:
            self._discard_samples()
            return np.empty(0, dtype=np.float32)
        stream = self._stream
        phase = "stop"
        try:
            if stream is None or not stream.active:
                raise RuntimeError("input stream stopped during capture")
            stream.stop(ignore_errors=False)
            phase = "finalize"
            # PortAudio has now quiesced the callback, so these values and the
            # block list form one stable snapshot of the completed capture.
            capture_started_at = self._capture_started_at
            input_frames = self._frames
            overflow = self._overflow
            capped = self._capped
            self._state = RecorderState.PREPARED
            audio = np.concatenate(self._blocks) if self._blocks else np.empty(0, dtype=np.float32)
            if self._device_rate != SAMPLE_RATE:
                audio = _resample_poly(audio, self._device_rate, SAMPLE_RATE)
            audio = audio.astype(np.float32, copy=False)
        except Exception as exc:
            failed_frames = self._frames
            failed_overflow = self._overflow
            failed_capped = self._capped
            log_failure(
                logger,
                logging.WARNING,
                "recorder: capture_failed",
                exc,
                safe=True,
                phase=phase,
                input_frames=failed_frames,
                overflow=int(failed_overflow),
                capped=int(failed_capped),
            )
            self._invalidate(reselect_default=True)
            raise
        self._discard_samples()
        elapsed = 0.0 if capture_started_at is None else time.perf_counter() - capture_started_at
        self._last_capture = CaptureStats(
            activate_ms=self._activation_ms,
            capture_seconds=elapsed,
            input_frames=input_frames,
            output_frames=int(audio.size),
            overflow=overflow,
            capped=capped,
        )
        logger.debug(
            fmt_event(
                "recorder",
                "captured",
                duration_seconds=round(elapsed, 3),
                input_frames=input_frames,
                output_frames=int(audio.size),
                rate_hz=self._device_rate,
                channels=self._channels,
                overflow=int(overflow),
                capped=int(capped),
            )
        )
        if capped:
            logger.warning(
                "recorder: capture_capped max_seconds=%d frames=%d",
                self._max_seconds,
                input_frames,
            )
        if overflow:
            logger.warning(
                "recorder: input_overflow input_frames=%d output_frames=%d capped=%d",
                input_frames,
                audio.size,
                int(capped),
            )
        return audio

    def close(self) -> None:
        """Release any active or stopped stream and discard buffered audio.

        Safe to call repeatedly. A later ``prepare`` may create a fresh stream.
        """
        self._invalidate(reselect_default=True)

    def _invalidate(self, *, reselect_default: bool) -> None:
        stream, self._stream = self._stream, None
        self._state = RecorderState.UNPREPARED
        # Clear immediately for privacy, then clear again after PortAudio has
        # terminated callbacks in case an already-running callback appended.
        self._discard_samples()
        if reselect_default and self._configured_device is None:
            self._selected_device = None
        try:
            if stream is not None:
                stream.close(ignore_errors=False)
        except Exception as exc:
            log_failure(logger, logging.WARNING, "recorder: close_failed", exc, safe=True)
        finally:
            self._discard_samples()

    def _discard_samples(self) -> None:
        self._blocks = []
        self._frames = 0
        self._capped = False
        self._overflow = False
        self._capture_started_at = None

    @property
    def last_capture(self) -> CaptureStats | None:
        """Stats for the most recently completed capture, or ``None``.

        Read on the hotkey thread in ``Daemon.on_key_up``, immediately after
        ``stop`` has returned its samples, so the utterance summary can carry
        the capture's cost without the daemon re-deriving it.
        """
        return self._last_capture

    @property
    def is_active(self) -> bool:
        return self._state is RecorderState.CAPTURING

    @property
    def is_prepared(self) -> bool:
        return self._state is RecorderState.PREPARED

    @property
    def state(self) -> RecorderState:
        return self._state
