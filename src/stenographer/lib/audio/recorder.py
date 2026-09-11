# SPDX-License-Identifier: GPL-3.0-or-later
"""Audio capture: the ``Recorder`` and the pure energy gate.

The PortAudio callback copies blocks and scalar clock metadata — never analysis. ``sounddevice``
is imported lazily inside ``Recorder.prepare`` so the pure helpers (the RMS gate
and the resampler) import without PortAudio present. Sample-rate and channel
fallback polyphase-resample the capture to the fixed ASR rate."""

from __future__ import annotations

import contextlib
import logging
import time
from collections import deque
from collections.abc import Callable
from typing import Any

import numpy as np

from stenographer.lib.audio.constants import SAMPLE_RATE
from stenographer.lib.audio.metrics import elapsed_ms, reduce_clock
from stenographer.lib.audio.records import CaptureStats
from stenographer.lib.audio.resample import _resample_poly
from stenographer.lib.audio.state import RecorderState
from stenographer.lib.logging.pipeline import fmt_event, log_failure

logger = logging.getLogger(__name__)


_FALLBACK_SAMPLE_RATES: tuple[int, ...] = (48000, 44100, 22050, 16000, 8000)


_FALLBACK_CHANNELS: tuple[int, ...] = (2, 1)


_ERR_BAD_CHANNELS = -9998


_ERR_BAD_SAMPLE_RATE = -9997


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
        self._device_name: str | None = None
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
        self._activation_started_at = 0.0
        self._clock_metadata: deque[tuple[float, float, int]] = deque(maxlen=8192)
        self._first_callback_at: float | None = None
        self._callback_count = 0
        self._overflow_count = 0
        self._recovered = False
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
                    self._device_name = None
                    with contextlib.suppress(Exception):
                        name = sounddevice.query_devices(self._selected_device, kind="input")[
                            "name"
                        ]
                        if isinstance(name, str):
                            self._device_name = name
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
        # Reset before start: callbacks may arrive before stream.start returns.
        # Recovery gets its own clock and samples, never a partial first attempt.
        self._blocks = []
        self._frames = 0
        self._overflow = False
        self._capped = False
        self._clock_metadata.clear()
        self._first_callback_at = None
        self._callback_count = 0
        self._overflow_count = 0
        self._recovered = recovery != "none"
        self._activation_started_at = started_at
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
            self._overflow_count += 1
        if self._capped:
            return
        callback_at = time.perf_counter()
        if self._first_callback_at is None:
            self._first_callback_at = callback_at
        self._callback_count += 1
        self._clock_metadata.append(
            (callback_at, getattr(time_info, "inputBufferAdcTime", 0.0), frames)
        )
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
        finalize_started_at = time.perf_counter()
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
            callback_clock = reduce_clock(
                self._clock_metadata,
                rate=self._device_rate,
                first_callback_at=self._first_callback_at,
            )
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
            first_callback_at=callback_clock.first_callback_at,
            activation_to_callback_ms=elapsed_ms(
                self._activation_started_at, callback_clock.first_callback_at
            ),
            max_adc_gap_ms=callback_clock.max_adc_gap_ms,
            adc_discontinuities=callback_clock.adc_discontinuities,
            input_rate=self._device_rate,
            device_name=self._device_name,
            channels=self._channels,
            finalize_ms=(time.perf_counter() - finalize_started_at) * 1000,
            callback_count=self._callback_count,
            callback_timing_count=callback_clock.timing_count,
            callback_metadata_dropped=max(0, self._callback_count - len(self._clock_metadata)),
            overflow_count=self._overflow_count,
            recovered=self._recovered,
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
