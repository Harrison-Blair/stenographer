# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import concurrent.futures
import ctypes
import functools
import logging
import os
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import numpy as np

from stenographer.asr.model import LazyModel, Model, SegmentInfo, TranscriptionResult, WordInfo

log = logging.getLogger(__name__)


class CancelledError(Exception):
    """Raised inside the worker thread when a job's ``cancel_event`` or
    :meth:`Worker.cancel` fires during an in-flight transcription."""


_UNLOAD = object()
"""Sentinel placed on the Worker queue by :meth:`Worker.request_unload` to
signal that the lazy model should be disposed on the worker thread."""


@dataclass
class Job:
    samples: np.ndarray
    future: (
        concurrent.futures.Future[TranscriptionResult] | concurrent.futures.Future[list[WordInfo]]
    )
    on_segment: Callable[[SegmentInfo], None] | None = None
    cancel_event: threading.Event | None = None
    kind: Literal["segments", "words"] = "segments"
    beam_size: int | None = None
    ignore_global_cancel: bool = False


class Worker:
    def __init__(
        self,
        model: Model | LazyModel,
        *,
        sample_rate: int = 16000,
    ) -> None:
        self._model = model
        self._sample_rate = sample_rate
        self._queue: queue.Queue[Job | object] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._cancel_event = threading.Event()
        self._close_lock = threading.Lock()
        self._model_closed = False

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
        cancel_event: threading.Event | None = None,
    ) -> concurrent.futures.Future[TranscriptionResult]:
        future: concurrent.futures.Future[TranscriptionResult] = concurrent.futures.Future()
        self._queue.put(
            Job(samples=samples, future=future, on_segment=on_segment, cancel_event=cancel_event)
        )
        return future

    def submit_words(
        self,
        samples: np.ndarray,
        *,
        beam_size: int | None = None,
        cancel_event: threading.Event | None = None,
        ignore_global_cancel: bool = False,
    ) -> concurrent.futures.Future[list[WordInfo]]:
        """Enqueue a single word-timestamped re-decode of *samples*.

        Used by the incremental driver: one job per interim re-decode of
        the growing utterance window.  Honors the same mid-job cancellation
        and lazy model loading as :meth:`submit`.

        *ignore_global_cancel* exempts the job from :meth:`cancel` so a
        shutdown that aborts in-flight interim re-decodes still lets the
        utterance's final decode finish. *cancel_event* is unaffected: a
        genuine abort must still stop the job.
        """
        future: concurrent.futures.Future[list[WordInfo]] = concurrent.futures.Future()
        self._queue.put(
            Job(
                samples=samples,
                future=future,
                cancel_event=cancel_event,
                kind="words",
                beam_size=beam_size,
                ignore_global_cancel=ignore_global_cancel,
            )
        )
        return future

    def request_unload(self, token: int) -> None:
        """Enqueue an idle-unload of the lazy model onto the worker thread.

        The actual disposal runs in :meth:`_run` (worker thread), where
        CTranslate2's ReplicaPool bound the model, so the C++ destructor
        can release the weights.  *token* is checked against the
        LazyModel's ``_load_generation`` to drop stale requests.
        """
        self._queue.put((_UNLOAD, token))

    def cancel(self) -> None:
        """Signal the in-flight transcription to abort at the next segment boundary.

        Non-blocking.  Does not tear down the worker thread; use
        :meth:`stop` for a full teardown.
        """
        self._cancel_event.set()

    def stop(self, timeout: float = 30.0) -> None:
        self._queue.put(None)
        thread = self._thread
        if thread is None:
            self._close_model()
            return
        thread.join(timeout=timeout)
        if thread.is_alive():
            # Inference may not observe cancellation until the model yields its
            # next segment. Closing it here would race that in-flight call; the
            # worker's finally block closes it once inference actually exits.
            log.warning("ASR worker did not stop within %.1fs; deferring model close", timeout)

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
        try:
            while True:
                job = self._queue.get()
                if job is None:
                    log.debug("ASR worker thread exiting")
                    return
                if isinstance(job, tuple) and len(job) == 2 and job[0] is _UNLOAD:
                    _sentinel, token = job
                    if isinstance(self._model, LazyModel):
                        self._model.do_unload_on_worker(token)
                    _trim_arena()
                    if __debug__ and os.environ.get("STENOGRAPHER_TRACE_UNLOAD") == "1":
                        from stenographer.asr.model import _read_rss_kb

                        log.info(
                            "trace-unload: after malloc_trim rss_kb=%s",
                            _read_rss_kb(),
                        )
                    continue

                def on_segment(
                    seg: SegmentInfo,
                    *,
                    _user_cb: Callable[[SegmentInfo], None] | None = job.on_segment,
                    _job_cancel: threading.Event | None = job.cancel_event,
                    _ignore_global: bool = job.ignore_global_cancel,
                ) -> None:
                    if self._cancel_event.is_set() and not _ignore_global:
                        raise CancelledError("transcription cancelled")
                    if _job_cancel is not None and _job_cancel.is_set():
                        raise CancelledError("transcription cancelled")
                    if _user_cb is not None:
                        _user_cb(seg)

                if (self._cancel_event.is_set() and not job.ignore_global_cancel) or (
                    job.cancel_event is not None and job.cancel_event.is_set()
                ):
                    log.debug("ASR worker: job cancelled before transcription")
                    job.future.set_exception(CancelledError("transcription cancelled"))
                    continue

                try:
                    if job.kind == "words":
                        result = self._model.transcribe_words(
                            job.samples,
                            beam_size=job.beam_size,
                            check_cancel=functools.partial(
                                self._check_cancel,
                                job.cancel_event,
                                ignore_global=job.ignore_global_cancel,
                            ),
                        )
                    else:
                        result = self._model.transcribe(
                            job.samples,
                            self._model.language,
                            self._model.beam_size,
                            on_segment=on_segment,
                        )
                except CancelledError as exc:
                    log.debug("ASR worker: transcription cancelled")
                    job.future.set_exception(exc)
                    continue
                except Exception as exc:
                    log.exception("ASR worker inference failed")
                    job.future.set_exception(exc)
                    continue
                job.future.set_result(result)
        finally:
            self._close_model()

    def _close_model(self) -> None:
        """Close the model exactly once, never concurrently with inference."""
        with self._close_lock:
            if self._model_closed:
                return
            self._model.close()
            self._model_closed = True

    def _check_cancel(
        self, job_cancel: threading.Event | None, *, ignore_global: bool = False
    ) -> None:
        """Raise :class:`CancelledError` if a global or per-job cancel fired."""
        if self._cancel_event.is_set() and not ignore_global:
            raise CancelledError("transcription cancelled")
        if job_cancel is not None and job_cancel.is_set():
            raise CancelledError("transcription cancelled")


def _trim_arena() -> None:
    """``malloc_trim(0)`` on the worker thread so freed scratch returns
    to the OS. Linux/glibc only; no-op elsewhere so the binary still
    runs in CI / non-glibc containers.
    """
    try:
        libc = ctypes.CDLL(None)
    except OSError:
        return
    trim = getattr(libc, "malloc_trim", None)
    if trim is None:
        return
    try:
        trim(0)
    except Exception as exc:
        log.debug("malloc_trim on worker thread failed: %s", exc)
