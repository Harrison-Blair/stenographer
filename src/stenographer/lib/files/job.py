# SPDX-License-Identifier: GPL-3.0-or-later
"""Synchronized state and progress for one file job."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from stenographer.lib.files.models import FileJobOptions, FileJobProgress
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.logging.pipeline import fmt_event

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from stenographer.lib.files.media import MediaInfo


class FileJob:
    """A queued or running job with thread-safe progress and cancellation."""

    def __init__(self, job_id: str, options: FileJobOptions, media_info: MediaInfo | None) -> None:
        self.id = job_id
        self.options = options
        self._media_info = media_info
        self._lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._finished = threading.Event()
        self._state = "queued"
        self._error: str | None = None
        self._session_id: str | None = None
        self._started_at: float | None = None
        self._progress = FileJobProgress("transcribe", 0, None, ())
        self._progress_listeners: list[Callable[[FileJobProgress], None]] = []

    @property
    def media_info(self) -> MediaInfo | None:
        with self._lock:
            return self._media_info

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def error(self) -> str | None:
        with self._lock:
            return self._error

    @property
    def session_id(self) -> str | None:
        """Return the session that holds the result once the job completes."""
        with self._lock:
            return self._session_id

    @property
    def started_at(self) -> float | None:
        with self._lock:
            return self._started_at

    @property
    def progress(self) -> FileJobProgress:
        with self._lock:
            return self._progress

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_event.is_set()

    def subscribe(self, listener: Callable[[FileJobProgress], None]) -> None:
        """Receive current and future progress snapshots."""
        with self._lock:
            self._progress_listeners.append(listener)
            progress = self._progress
        self._notify_progress((listener,), progress)

    def cancel(self) -> bool:
        """Request cancellation at the next phrase boundary."""
        with self._lock:
            if self._state in {"completed", "cancelled", "failed", "needs_ffmpeg"}:
                return False
            first_request = not self._cancel_event.is_set()
            self._cancel_event.set()
        if first_request:
            log.info(fmt_event("files", "job_cancel_requested", job_id=self.id))
        return True

    def wait(self, timeout: float | None = None) -> str:
        """Wait for a terminal state and return the current state."""
        self._finished.wait(timeout)
        return self.state

    def _set_media_info(self, media_info: MediaInfo) -> None:
        with self._lock:
            self._media_info = media_info

    def _start(self) -> bool:
        with self._lock:
            if self._cancel_event.is_set():
                self._state = "cancelled"
                self._finished.set()
                started = False
            else:
                self._state = "running"
                self._started_at = time.monotonic()
                started = True
        if started:
            log.info(fmt_event("files", "job_started", job_id=self.id))
        else:
            log.info(fmt_event("files", "job_cancelled", job_id=self.id))
        return started

    def _update(
        self,
        stage: str,
        percent: int,
        eta_seconds: float | None,
        lines: tuple[TranscriptLine, ...],
    ) -> None:
        with self._lock:
            stage_changed = self._progress.stage != stage
            self._progress = FileJobProgress(
                stage,
                min(100, max(0, int(percent))),
                None if eta_seconds is None else max(0.0, eta_seconds),
                tuple(lines),
            )
            progress = self._progress
            listeners = tuple(self._progress_listeners)
        if stage_changed:
            log.info(fmt_event("files", "job_stage", job_id=self.id, stage=stage))
        self._notify_progress(listeners, progress)

    def _complete(self, session_id: str, lines: tuple[TranscriptLine, ...]) -> None:
        with self._lock:
            self._session_id = session_id
            self._progress = FileJobProgress("save", 100, 0.0, lines)
            self._state = "completed"
            self._finished.set()
            progress = self._progress
            listeners = tuple(self._progress_listeners)
        log.info(fmt_event("files", "job_completed", job_id=self.id))
        self._notify_progress(listeners, progress)

    def _cancelled(self, lines: tuple[TranscriptLine, ...]) -> None:
        with self._lock:
            self._progress = FileJobProgress(
                self._progress.stage, self._progress.percent, None, lines
            )
            self._state = "cancelled"
            self._finished.set()
            progress = self._progress
            listeners = tuple(self._progress_listeners)
        log.info(fmt_event("files", "job_cancelled", job_id=self.id))
        self._notify_progress(listeners, progress)

    def _fail(self, error: str) -> None:
        with self._lock:
            self._error = error
            self._state = "failed"
            self._finished.set()
        log.info(fmt_event("files", "job_failed", job_id=self.id, error=error))

    def _needs_ffmpeg(self) -> None:
        with self._lock:
            self._error = "needs ffmpeg"
            self._state = "needs_ffmpeg"
            self._finished.set()
        log.info(fmt_event("files", "job_blocked", job_id=self.id, reason="needs_ffmpeg"))

    @staticmethod
    def _notify_progress(
        listeners: tuple[Callable[[FileJobProgress], None], ...], progress: FileJobProgress
    ) -> None:
        for listener in listeners:
            try:
                listener(progress)
            except Exception as exc:
                log.warning("files: progress_listener_failed error=%s", type(exc).__name__)
