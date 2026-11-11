# SPDX-License-Identifier: GPL-3.0-or-later
"""Dictation capture: the ``Recorder``.

Each ``start`` makes a new platform microphone capture, so each dictation owns
its own capture child and no microphone stays open between dictations.
``stop`` ends the capture and returns after its last block, so the audio up to
the stop is complete. ``abandon`` detaches the capture and ends it on a
background thread, so the next ``start`` never waits for it; ``close`` ends
every capture, including the ones that still end in the background."""

from __future__ import annotations

import contextlib
import logging
import threading
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


class _Take:
    """One capture and what its reader thread delivered.

    The capture's callback is bound to its take, so a block or a failure from
    an abandoned capture can never reach a later dictation.
    """

    def __init__(
        self,
        capture: MicCapture,
        *,
        epoch: int,
        max_frames: int,
        on_block: Callable[[np.ndarray, int, int], None] | None,
        on_failure: Callable[[], None] | None,
    ) -> None:
        self.capture = capture
        self.epoch = epoch
        self.max_frames = max_frames
        self.on_block = on_block
        self.on_failure = on_failure
        self.abandoned = False
        self.blocks: list[np.ndarray] = []
        self.frames = 0
        self.capped = False
        self.failure: MicCaptureError | None = None
        self.started_at = 0.0
        self.activation_ms = 0.0
        self.capture_started_at: float | None = None
        self.first_block_at: float | None = None
        self.block_count = 0

    def receive(self, item: np.ndarray | MicCaptureError) -> None:
        """Reader thread: keep a block, or remember why the capture stopped."""
        if self.abandoned:
            return
        if isinstance(item, MicCaptureError):
            self.failure = item
            if self.on_failure is not None:
                with contextlib.suppress(Exception):
                    self.on_failure()
            return
        if self.capped:
            return
        if self.first_block_at is None:
            self.first_block_at = time.perf_counter()
        self.block_count += 1
        self.blocks.append(item)
        if self.on_block is not None:
            # The optional sink may only replace a latest-only in-memory slot.
            with contextlib.suppress(Exception):
                self.on_block(item, SAMPLE_RATE, self.epoch)
        self.frames += item.shape[0]
        if self.max_frames and self.frames >= self.max_frames:
            self.capped = True

    def stats(self, finalize_started_at: float, target: str | None) -> CaptureStats:
        elapsed = (
            0.0
            if self.capture_started_at is None
            else time.perf_counter() - self.capture_started_at
        )
        return CaptureStats(
            activate_ms=self.activation_ms,
            capture_seconds=elapsed,
            input_frames=self.frames,
            output_frames=self.frames,
            capped=self.capped,
            first_callback_at=self.first_block_at,
            activation_to_callback_ms=(
                None
                if self.first_block_at is None
                else (self.first_block_at - self.started_at) * 1000
            ),
            device_name=target,
            finalize_ms=(time.perf_counter() - finalize_started_at) * 1000,
            callback_count=self.block_count,
        )


class Recorder:
    """Captures one dictation at a time as a 1-D float32 array at the ASR rate.

    *capture_factory* makes a new platform capture for each ``start``.
    *on_block* gets each block for the level meter.
    """

    def __init__(
        self,
        *,
        capture_factory: Callable[[], MicCapture],
        device: str | None,
        max_seconds: int,
        on_block: Callable[[np.ndarray, int, int], None] | None = None,
    ) -> None:
        self._capture_factory = capture_factory
        self._target = capture_target(device)
        self._max_seconds = max_seconds
        self._on_block = on_block
        self._take: _Take | None = None
        self._stream_epoch = 0
        self._ending: list[threading.Thread] = []
        # One utterance at a time (a daemon invariant), so the last completed
        # capture is unambiguously the one the pipeline thread is about to run.
        self._last_capture: CaptureStats | None = None

    @property
    def capturing(self) -> bool:
        return self._take is not None

    def start(self, on_failure: Callable[[], None] | None = None) -> None:
        """Start a new capture child; raise when it cannot start.

        *on_failure* is called on the capture's reader thread when this capture
        stops by itself; the next ``stop`` then raises.
        """
        if self._take is not None:
            raise RuntimeError("recorder is already capturing")
        self._last_capture = None
        self._stream_epoch += 1
        take = _Take(
            self._capture_factory(),
            epoch=self._stream_epoch,
            max_frames=self._max_seconds * SAMPLE_RATE,
            on_block=self._on_block,
            on_failure=on_failure,
        )
        take.started_at = time.perf_counter()
        take.capture.start(self._target, take.receive)
        take.activation_ms = (time.perf_counter() - take.started_at) * 1000.0
        take.capture_started_at = time.perf_counter()
        self._take = take
        # DEBUG, not INFO: this runs under the daemon's state lock, and the
        # numbers reach the log through the utterance summary line instead.
        logger.debug(fmt_event("recorder", "activated", duration_ms=round(take.activation_ms, 1)))

    def stop(self) -> np.ndarray:
        """End the capture and return its samples, up to the stop.

        Raise when the capture stopped by itself; its samples are discarded.
        Calling ``stop`` while not capturing is harmless and returns empty.
        """
        take, self._take = self._take, None
        if take is None:
            return np.empty(0, dtype=np.float32)
        finalize_started_at = time.perf_counter()
        try:
            take.capture.stop()
            if take.failure is not None:
                raise take.failure
        except Exception as exc:
            log_failure(
                logger,
                logging.WARNING,
                "recorder: capture_failed",
                exc,
                safe=True,
                phase="stop",
                input_frames=take.frames,
                capped=int(take.capped),
            )
            take.blocks.clear()
            raise
        audio = np.concatenate(take.blocks) if take.blocks else np.empty(0, dtype=np.float32)
        take.blocks.clear()
        stats = take.stats(finalize_started_at, self._target)
        self._last_capture = stats
        logger.debug(
            fmt_event(
                "recorder",
                "captured",
                duration_seconds=round(stats.capture_seconds, 3),
                input_frames=stats.input_frames,
                output_frames=stats.output_frames,
                rate_hz=SAMPLE_RATE,
                channels=1,
                capped=int(stats.capped),
            )
        )
        if stats.capped:
            logger.warning(
                "recorder: capture_capped max_seconds=%d frames=%d",
                self._max_seconds,
                stats.input_frames,
            )
        return audio

    def abandon(self) -> None:
        """Discard the capture's audio and end its child on a background thread.

        Returns at once. ``last_capture`` gets the counters up to now. Blocks
        and a failure that the child still delivers are ignored.
        """
        take, self._take = self._take, None
        if take is None:
            return
        take.abandoned = True
        self._last_capture = take.stats(time.perf_counter(), self._target)
        take.blocks.clear()
        self._ending = [thread for thread in self._ending if thread.is_alive()]
        thread = threading.Thread(
            target=self._end, args=(take.capture,), name="stenographer-capture-end", daemon=True
        )
        self._ending.append(thread)
        thread.start()

    @staticmethod
    def _end(capture: MicCapture) -> None:
        try:
            capture.stop()
        except Exception as exc:
            log_failure(logger, logging.WARNING, "recorder: close_failed", exc, safe=True)

    def close(self) -> None:
        """End every capture, wait for the ones that end in the background, discard audio.

        Safe to call repeatedly.
        """
        take, self._take = self._take, None
        if take is not None:
            take.abandoned = True
            take.blocks.clear()
            self._end(take.capture)
        ending, self._ending = self._ending, []
        for thread in ending:
            thread.join()

    @property
    def last_capture(self) -> CaptureStats | None:
        """Stats for the most recently completed or abandoned capture, or ``None``.

        Read under the daemon's state lock right after ``stop`` or ``abandon``,
        so the utterance summary can carry the capture's cost without the
        daemon re-deriving it.
        """
        return self._last_capture
