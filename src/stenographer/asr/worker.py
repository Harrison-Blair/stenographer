# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import concurrent.futures
import logging
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from stenographer.asr.model import LazyModel, Model, SegmentInfo, TranscriptionResult

log = logging.getLogger(__name__)


class _CancelledError(Exception):
    """Raised inside the worker thread when :meth:`Worker.cancel` is called
    during an in-flight transcription."""


@dataclass
class Job:
    samples: np.ndarray
    future: concurrent.futures.Future[TranscriptionResult]
    on_segment: Callable[[SegmentInfo], None] | None = None


class Worker:
    def __init__(self, model: Model | LazyModel, timeout_seconds: float = 300.0) -> None:
        self._model = model
        self.timeout_seconds = timeout_seconds
        self._queue: queue.Queue[Job | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._cancel_event = threading.Event()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="asr-worker", daemon=True)
        self._thread.start()

    def submit(
        self,
        samples: np.ndarray,
        *,
        on_segment: Callable[[SegmentInfo], None] | None = None,
    ) -> concurrent.futures.Future[TranscriptionResult]:
        future: concurrent.futures.Future[TranscriptionResult] = concurrent.futures.Future()
        self._queue.put(Job(samples=samples, future=future, on_segment=on_segment))
        return future

    def cancel(self) -> None:
        """Signal the in-flight transcription to abort at the next segment boundary.

        Non-blocking.  Does not tear down the worker thread; use
        :meth:`stop` for a full teardown.
        """
        self._cancel_event.set()

    def stop(self, timeout: float = 30.0) -> None:
        self._queue.put(None)
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        self._model.close()

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def ensure_model_loaded(
        self,
        on_loaded: Callable[[], None] | None = None,
        on_unloaded: Callable[[], None] | None = None,
    ) -> None:
        if isinstance(self._model, LazyModel):
            self._model.ensure_loaded(on_loaded=on_loaded, on_unloaded=on_unloaded)

    def is_model_loaded(self) -> bool:
        if isinstance(self._model, LazyModel):
            return self._model.is_loaded()
        return True

    def _run(self) -> None:
        log.debug("ASR worker thread started")
        while True:
            job = self._queue.get()
            if job is None:
                log.debug("ASR worker thread exiting")
                return

            def on_segment(
                seg: SegmentInfo,
                *,
                _user_cb: Callable[[SegmentInfo], None] | None = job.on_segment,
            ) -> None:
                if self._cancel_event.is_set():
                    raise _CancelledError("transcription cancelled")
                if _user_cb is not None:
                    _user_cb(seg)

            try:
                result = self._model.transcribe(
                    job.samples,
                    self._model.language,
                    self._model.beam_size,
                    on_segment=on_segment,
                )
            except _CancelledError as exc:
                log.debug("ASR worker: transcription cancelled")
                job.future.set_exception(exc)
                continue
            except Exception as exc:
                log.exception("ASR worker inference failed")
                job.future.set_exception(exc)
                continue
            job.future.set_result(result)
