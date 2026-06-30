# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import concurrent.futures
import logging
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from stenographer.asr.model import Model, SegmentInfo, TranscriptionResult

log = logging.getLogger(__name__)


@dataclass
class Job:
    samples: np.ndarray
    future: concurrent.futures.Future[TranscriptionResult]
    on_segment: Callable[[SegmentInfo], None] | None = None


class Worker:
    def __init__(self, model: Model, timeout_seconds: float = 300.0) -> None:
        self._model = model
        self.timeout_seconds = timeout_seconds
        self._queue: queue.Queue[Job | None] = queue.Queue()
        self._thread: threading.Thread | None = None

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

    def stop(self, timeout: float = 30.0) -> None:
        self._queue.put(None)
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def _run(self) -> None:
        log.debug("ASR worker thread started")
        while True:
            job = self._queue.get()
            if job is None:
                log.debug("ASR worker thread exiting")
                return
            try:
                result = self._model.transcribe(
                    job.samples,
                    self._model.language,
                    self._model.beam_size,
                    on_segment=job.on_segment,
                )
            except Exception as exc:
                log.exception("ASR worker inference failed")
                job.future.set_exception(exc)
                continue
            job.future.set_result(result)
