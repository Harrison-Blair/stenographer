# SPDX-License-Identifier: GPL-3.0-or-later
"""Dictation capture: the ``Recorder``.

Each ``start`` starts a platform microphone capture and each ``stop`` ends
it, so no microphone stays open between dictations. The capture delivers
16 kHz mono float32 blocks on its reader thread; ``stop`` returns after the
last block, so the samples and counters it reads are complete."""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Callable

import numpy as np

from stenographer.lib.audio.constants import SAMPLE_RATE
from stenographer.lib.audio.device_setting import capture_target
from stenographer.lib.audio.records import CaptureStats
from stenographer.lib.logging.pipeline import fmt_event, log_failure
from stenographer.lib.platform.errors import MicCaptureError
from stenographer.lib.platform.mic_capture import MicCapture

logger = logging.getLogger(__name__)


class Recorder:
    """Captures one dictation as a 1-D float32 array at the ASR rate.

    *on_block* gets each block for the level meter. *on_failure* is called on
    the capture's reader thread when the capture stops by itself; the next
    ``stop`` then raises.
    """

    def __init__(
        self,
        *,
        capture: MicCapture,
        device: str | None,
        max_seconds: int,
        on_block: Callable[[np.ndarray, int, int], None] | None = None,
        on_failure: Callable[[], None] | None = None,
    ) -> None:
        self._capture = capture
        self._target = capture_target(device)
        self._max_frames = max_seconds * SAMPLE_RATE
        self._max_seconds = max_seconds
        self._on_block = on_block
        self._on_failure = on_failure
        self._capturing = False
        self._stream_epoch = 0
        self._blocks: list[np.ndarray] = []
        self._frames = 0
        self._capped = False
        self._failure: MicCaptureError | None = None
        self._capture_started_at: float | None = None
        self._activation_started_at = 0.0
        self._activation_ms = 0.0
        self._first_block_at: float | None = None
        self._block_count = 0
        # One utterance at a time (a daemon invariant), so the last completed
        # capture is unambiguously the one the pipeline thread is about to run.
        self._last_capture: CaptureStats | None = None

    @property
    def capturing(self) -> bool:
        return self._capturing

    def start(self) -> None:
        """Start the capture child; raise when it cannot start."""
        if self._capturing:
            raise RuntimeError("recorder is already capturing")
        # Reset before start: blocks may arrive before capture.start returns.
        self._discard_samples()
        self._failure = None
        self._first_block_at = None
        self._block_count = 0
        self._last_capture = None
        self._stream_epoch += 1
        started_at = time.perf_counter()
        self._activation_started_at = started_at
        self._capture.start(self._target, self._on_item)
        self._activation_ms = (time.perf_counter() - started_at) * 1000.0
        self._capture_started_at = time.perf_counter()
        self._capturing = True
        # DEBUG, not INFO: this runs under the daemon's state lock, and the
        # numbers reach the log through the utterance summary line instead.
        logger.debug(fmt_event("recorder", "activated", duration_ms=round(self._activation_ms, 1)))

    def _on_item(self, item: np.ndarray | MicCaptureError) -> None:
        """Reader thread: keep a block, or remember why the capture stopped."""
        if isinstance(item, MicCaptureError):
            self._failure = item
            if self._on_failure is not None:
                with contextlib.suppress(Exception):
                    self._on_failure()
            return
        if self._capped:
            return
        if self._first_block_at is None:
            self._first_block_at = time.perf_counter()
        self._block_count += 1
        self._blocks.append(item)
        if self._on_block is not None:
            # The optional sink may only replace a latest-only in-memory slot.
            with contextlib.suppress(Exception):
                self._on_block(item, SAMPLE_RATE, self._stream_epoch)
        self._frames += item.shape[0]
        if self._max_frames and self._frames >= self._max_frames:
            self._capped = True

    def stop(self) -> np.ndarray:
        """End the capture and return its samples.

        Raise when the capture stopped by itself; its samples are discarded.
        Calling ``stop`` while not capturing is harmless and returns empty.
        """
        if not self._capturing:
            self._discard_samples()
            return np.empty(0, dtype=np.float32)
        finalize_started_at = time.perf_counter()
        self._capturing = False
        try:
            self._capture.stop()
            if self._failure is not None:
                raise self._failure
        except Exception as exc:
            log_failure(
                logger,
                logging.WARNING,
                "recorder: capture_failed",
                exc,
                safe=True,
                phase="stop",
                input_frames=self._frames,
                capped=int(self._capped),
            )
            self._discard_samples()
            raise
        capture_started_at = self._capture_started_at
        frames = self._frames
        capped = self._capped
        audio = np.concatenate(self._blocks) if self._blocks else np.empty(0, dtype=np.float32)
        self._discard_samples()
        elapsed = 0.0 if capture_started_at is None else time.perf_counter() - capture_started_at
        self._last_capture = CaptureStats(
            activate_ms=self._activation_ms,
            capture_seconds=elapsed,
            input_frames=frames,
            output_frames=frames,
            capped=capped,
            first_callback_at=self._first_block_at,
            activation_to_callback_ms=(
                None
                if self._first_block_at is None
                else (self._first_block_at - self._activation_started_at) * 1000
            ),
            device_name=self._target,
            finalize_ms=(time.perf_counter() - finalize_started_at) * 1000,
            callback_count=self._block_count,
        )
        logger.debug(
            fmt_event(
                "recorder",
                "captured",
                duration_seconds=round(elapsed, 3),
                input_frames=frames,
                output_frames=frames,
                rate_hz=SAMPLE_RATE,
                channels=1,
                capped=int(capped),
            )
        )
        if capped:
            logger.warning(
                "recorder: capture_capped max_seconds=%d frames=%d",
                self._max_seconds,
                frames,
            )
        return audio

    def close(self) -> None:
        """End any capture and discard buffered audio. Safe to call repeatedly."""
        self._capturing = False
        try:
            self._capture.stop()
        except Exception as exc:
            log_failure(logger, logging.WARNING, "recorder: close_failed", exc, safe=True)
        finally:
            self._discard_samples()

    def _discard_samples(self) -> None:
        self._blocks = []
        self._frames = 0
        self._capped = False
        self._capture_started_at = None

    @property
    def last_capture(self) -> CaptureStats | None:
        """Stats for the most recently completed capture, or ``None``.

        Read on the hotkey thread in ``Daemon.on_key_up``, immediately after
        ``stop`` has returned its samples, so the utterance summary can carry
        the capture's cost without the daemon re-deriving it.
        """
        return self._last_capture
