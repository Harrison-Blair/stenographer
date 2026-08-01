# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import concurrent.futures
import contextlib
import ctypes
import logging
import logging.handlers
import multiprocessing
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import numpy as np

from stenographer.asr.model import (
    Model,
    PathologicalOutputError,
    SegmentInfo,
    TranscriptionResult,
    WordInfo,
)
from stenographer.config import AsrConfig

log = logging.getLogger(__name__)


class CancelledError(Exception):
    """Raised when a job's cancellation is signalled during an in-flight
    transcription."""


class ASRTimeoutError(TimeoutError):
    """A decode exceeded its absolute deadline."""


class ASRProcessError(RuntimeError):
    """The native inference child crashed or became unavailable."""


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


@dataclass
class _ProcessJob:
    samples: np.ndarray
    future: (
        concurrent.futures.Future[TranscriptionResult] | concurrent.futures.Future[list[WordInfo]]
    )
    kind: Literal["segments", "words"]
    priority: Literal["interim", "final"]
    sequence: int
    interim_generation: int
    deadline: float | None = None
    beam_size: int | None = None
    on_segment: Callable[[SegmentInfo], None] | None = None
    cancel_event: threading.Event | None = None
    ignore_global_cancel: bool = False


def _inference_process_main(
    cfg: AsrConfig,
    eager: bool,
    idle_unload_seconds: float | None,
    commands,
    responses,
    log_records,
) -> None:
    """Own the native model and service commands inside a spawned process."""
    root = logging.getLogger()
    root.handlers = [logging.handlers.QueueHandler(log_records)]
    root.setLevel(logging.DEBUG)
    model: Model | None = None
    last_used = time.monotonic()

    def load() -> Model:
        nonlocal model, last_used
        if model is None:
            model = Model(cfg)
            responses.put(("loaded",))
        last_used = time.monotonic()
        return model

    def unload() -> None:
        nonlocal model
        if model is not None:
            model.close()
            model = None
            _trim_arena()
            responses.put(("unloaded",))

    try:
        if eager:
            try:
                load()
            except BaseException as exc:
                responses.put(("load_error", type(exc).__name__, str(exc)))
                return
        while True:
            timeout = None
            if model is not None and idle_unload_seconds and idle_unload_seconds > 0:
                timeout = max(0.0, idle_unload_seconds - (time.monotonic() - last_used))
            try:
                command = commands.get(timeout=timeout)
            except queue.Empty:
                unload()
                continue
            name = command[0]
            if name == "stop":
                return
            if name == "load":
                try:
                    load()
                except BaseException as exc:
                    responses.put(("load_error", type(exc).__name__, str(exc)))
                continue
            if name == "unload":
                unload()
                continue
            if name != "job":
                continue
            _name, job_id, samples, kind, beam_size = command
            try:
                impl = load()
                if kind == "words":
                    result = impl.transcribe_words(samples, beam_size=beam_size)
                else:
                    result = impl.transcribe(
                        samples,
                        impl.language,
                        impl.beam_size if beam_size is None else beam_size,
                    )
                last_used = time.monotonic()
                responses.put(("result", job_id, result))
            except PathologicalOutputError as exc:
                responses.put(("error", job_id, "pathological", str(exc)))
            except BaseException as exc:
                logging.getLogger(__name__).exception("ASR inference failed in child")
                responses.put(("error", job_id, "inference", f"{type(exc).__name__}: {exc}"))
    finally:
        if model is not None:
            model.close()


class ProcessWorker:
    """Future-based ASR worker backed by a restartable spawned child process.

    The coordinator thread owns job ordering and deadlines. The child owns the
    faster-whisper/CTranslate2 model exclusively, so timeout and cancellation
    can safely terminate native inference without destabilizing the daemon.
    """

    def __init__(
        self,
        cfg: AsrConfig,
        *,
        sample_rate: int = 16000,
        eager: bool | None = None,
        child_target: Callable = _inference_process_main,
    ) -> None:
        self._cfg = cfg
        self._sample_rate = sample_rate
        self._eager = cfg.mode == "eager" if eager is None else eager
        self._child_target = child_target
        self._ctx = multiprocessing.get_context("spawn")
        self._jobs: queue.PriorityQueue[tuple[int, int, _ProcessJob | None]] = queue.PriorityQueue()
        self._sequence = 0
        self._manager: threading.Thread | None = None
        self._log_thread: threading.Thread | None = None
        self._process: multiprocessing.Process | None = None
        self._commands = None
        self._responses = None
        self._log_records = self._ctx.Queue()
        self._state_lock = threading.RLock()
        self._submit_lock = threading.Lock()
        self._active: _ProcessJob | None = None
        self._interim_generation = 0
        self._supersede = threading.Event()
        self._global_cancel = threading.Event()
        self._force_stop = threading.Event()
        self._stopping = False
        self._loaded = False
        self._ready = threading.Event()
        self._load_error: ASRProcessError | None = None
        self._on_loaded: Callable[[], None] | None = None
        self._on_unloaded: Callable[[], None] | None = None

    def start(self) -> None:
        if self._manager is not None and self._manager.is_alive():
            return
        with self._state_lock:
            self._spawn_child()
        self._log_thread = threading.Thread(
            target=self._forward_logs, name="asr-log-forwarder", daemon=True
        )
        self._log_thread.start()
        self._manager = threading.Thread(
            target=self._run_manager, name="asr-process-worker", daemon=True
        )
        self._manager.start()
        if self._eager:
            self._ready.wait()
            if self._load_error is not None:
                raise self._load_error

    def submit(
        self,
        samples: np.ndarray,
        *,
        on_segment: Callable[[SegmentInfo], None] | None = None,
        cancel_event: threading.Event | None = None,
        deadline: float | None = None,
        priority: Literal["interim", "final"] = "final",
    ) -> concurrent.futures.Future[TranscriptionResult]:
        future: concurrent.futures.Future[TranscriptionResult] = concurrent.futures.Future()
        self._enqueue_process_job(
            samples,
            future,
            kind="segments",
            priority=priority,
            deadline=deadline,
            on_segment=on_segment,
            cancel_event=cancel_event,
        )
        return future

    def submit_words(
        self,
        samples: np.ndarray,
        *,
        beam_size: int | None = None,
        cancel_event: threading.Event | None = None,
        ignore_global_cancel: bool = False,
        deadline: float | None = None,
        priority: Literal["interim", "final"] = "interim",
    ) -> concurrent.futures.Future[list[WordInfo]]:
        future: concurrent.futures.Future[list[WordInfo]] = concurrent.futures.Future()
        self._enqueue_process_job(
            samples,
            future,
            kind="words",
            priority=priority,
            deadline=deadline,
            beam_size=beam_size,
            cancel_event=cancel_event,
            ignore_global_cancel=ignore_global_cancel,
        )
        return future

    def _enqueue_process_job(
        self,
        samples: np.ndarray,
        future,
        *,
        kind: Literal["segments", "words"],
        priority: Literal["interim", "final"],
        deadline: float | None,
        beam_size: int | None = None,
        on_segment: Callable[[SegmentInfo], None] | None = None,
        cancel_event: threading.Event | None = None,
        ignore_global_cancel: bool = False,
    ) -> None:
        with self._submit_lock:
            if self._stopping:
                future.set_exception(CancelledError("worker stopping; job rejected"))
                return
            self._sequence += 1
            job = _ProcessJob(
                samples=samples,
                future=future,
                kind=kind,
                priority=priority,
                sequence=self._sequence,
                interim_generation=self._interim_generation,
                deadline=deadline,
                beam_size=beam_size,
                on_segment=on_segment,
                cancel_event=cancel_event,
                ignore_global_cancel=ignore_global_cancel,
            )
            rank = 0 if priority == "final" else 1
            self._jobs.put((rank, job.sequence, job))

    def supersede_interim(self) -> None:
        """Cancel queued interim jobs and tear down an active native decode."""
        with self._state_lock:
            self._interim_generation += 1
            if self._active is not None and self._active.priority == "interim":
                self._supersede.set()

    def cancel(self) -> None:
        self._global_cancel.set()
        self.supersede_interim()

    def stop(self, timeout: float = 30.0) -> None:
        with self._submit_lock:
            self._stopping = True
            self._sequence += 1
            self._jobs.put((99, self._sequence, None))
        manager = self._manager
        if manager is not None:
            manager.join(timeout=max(0.0, timeout))
        if manager is not None and manager.is_alive():
            self._force_stop.set()
            self._terminate_child()
            manager.join(timeout=1.0)
        self._fail_process_jobs(CancelledError("worker stopped"))
        self._log_records.put(None)
        if self._log_thread is not None:
            self._log_thread.join(timeout=1.0)

    @property
    def is_running(self) -> bool:
        manager = self._manager
        return manager is not None and manager.is_alive()

    def ensure_model_loaded(
        self,
        on_loaded: Callable[[], None] | None = None,
        on_unloaded: Callable[[], None] | None = None,
    ) -> None:
        with self._state_lock:
            if on_loaded is not None:
                self._on_loaded = on_loaded
            if on_unloaded is not None:
                self._on_unloaded = on_unloaded
            if self._loaded:
                return
            self._ensure_child()
            self._commands.put(("load",))

    def is_model_loaded(self) -> bool:
        with self._state_lock:
            return self._loaded

    def request_unload(self) -> None:
        with self._state_lock:
            if self._process is not None and self._process.is_alive():
                self._commands.put(("unload",))

    def _run_manager(self) -> None:
        try:
            while True:
                if self._force_stop.is_set():
                    break
                self._drain_state_messages()
                try:
                    _rank, _sequence, job = self._jobs.get(timeout=0.05)
                except queue.Empty:
                    if self._stopping:
                        break
                    process = self._process
                    if process is not None and not process.is_alive():
                        if self._eager and not self._ready.is_set():
                            self._load_error = ASRProcessError(
                                "ASR child exited while loading the model"
                            )
                            self._ready.set()
                        self._discard_child()
                    continue
                if job is None:
                    break
                if job.priority == "interim" and job.interim_generation != self._interim_generation:
                    self._resolve_exception(job, CancelledError("interim superseded"))
                    continue
                if self._job_cancelled(job):
                    self._resolve_exception(job, CancelledError("transcription cancelled"))
                    continue
                if job.deadline is not None and time.monotonic() >= job.deadline:
                    self._resolve_exception(job, ASRTimeoutError("ASR deadline expired"))
                    continue
                self._run_process_job(job)
        finally:
            self._terminate_child(graceful=True)
            self._fail_process_jobs(CancelledError("worker stopped"))

    def _run_process_job(self, job: _ProcessJob) -> None:
        with self._state_lock:
            self._active = job
            self._supersede.clear()
        try:
            with self._state_lock:
                self._ensure_child()
                process = self._process
                commands = self._commands
                responses = self._responses
            assert process is not None
            commands.put(("job", job.sequence, job.samples, job.kind, job.beam_size))
            while True:
                if self._abort_active_job(job, process):
                    return
                try:
                    message = responses.get(timeout=0.02)
                except queue.Empty:
                    continue
                if self._dispatch_response(job, message):
                    return
        except Exception as exc:
            log.exception("ASR process coordinator failed")
            self._resolve_exception(job, ASRProcessError(f"ASR coordinator failed: {exc}"))
            self._terminate_child()
        finally:
            with self._state_lock:
                self._active = None
                self._supersede.clear()

    def _abort_active_job(self, job: _ProcessJob, process: multiprocessing.Process) -> bool:
        """Apply the per-iteration abort guards; return True when a guard has
        resolved the job and the poll loop should exit."""
        if self._force_stop.is_set():
            self._resolve_exception(job, CancelledError("worker stopped"))
            self._terminate_child()
            return True
        if self._job_cancelled(job) or (job.priority == "interim" and self._supersede.is_set()):
            self._resolve_exception(job, CancelledError("transcription cancelled"))
            self._terminate_child()
            return True
        if job.deadline is not None and time.monotonic() >= job.deadline:
            self._resolve_exception(job, ASRTimeoutError("ASR deadline expired"))
            self._terminate_child()
            return True
        if not process.is_alive():
            self._discard_child()
            self._resolve_exception(job, ASRProcessError("ASR child exited during inference"))
            return True
        return False

    def _dispatch_response(self, job: _ProcessJob, message) -> bool:
        """Route one child response for the active job; return True when the
        job is resolved and the poll loop should exit."""
        name = message[0]
        if name in {"loaded", "unloaded", "load_error"}:
            self._handle_state_message(message)
            if name == "load_error":
                self._resolve_exception(job, self._load_error or ASRProcessError("load failed"))
                return True
            return False
        if len(message) < 2 or message[1] != job.sequence:
            return False
        if name == "result":
            result = message[2]
            try:
                if job.on_segment is not None and isinstance(result, TranscriptionResult):
                    for segment in result.segments:
                        job.on_segment(segment)
                if not job.future.done():
                    job.future.set_result(result)
            except Exception as exc:
                self._resolve_exception(job, exc)
            return True
        if name == "error":
            _name, _job_id, error_kind, detail = message
            if error_kind == "pathological":
                exc: Exception = PathologicalOutputError(detail)
            else:
                exc = ASRProcessError(detail)
            self._resolve_exception(job, exc)
            if error_kind != "pathological":
                self._terminate_child()
            return True
        return False

    def _job_cancelled(self, job: _ProcessJob) -> bool:
        return (
            job.future.cancelled()
            or (self._global_cancel.is_set() and not job.ignore_global_cancel)
            or (job.cancel_event is not None and job.cancel_event.is_set())
        )

    @staticmethod
    def _resolve_exception(job: _ProcessJob, exc: BaseException) -> None:
        if not job.future.done():
            job.future.set_exception(exc)

    def _spawn_child(self) -> None:
        self._commands = self._ctx.Queue()
        self._responses = self._ctx.Queue()
        self._loaded = False
        self._ready.clear()
        self._load_error = None
        self._process = self._ctx.Process(
            target=self._child_target,
            args=(
                self._cfg,
                self._eager,
                self._cfg.idle_unload_seconds or None,
                self._commands,
                self._responses,
                self._log_records,
            ),
            name="asr-inference",
            daemon=True,
        )
        self._process.start()

    def _ensure_child(self) -> None:
        if self._process is None or not self._process.is_alive():
            self._discard_child()
            self._spawn_child()

    def _terminate_child(self, *, graceful: bool = False) -> None:
        with self._state_lock:
            process = self._process
            commands = self._commands
            if process is None:
                return
            if graceful and process.is_alive():
                commands.put(("stop",))
                process.join(timeout=0.5)
            if process.is_alive():
                process.terminate()
                process.join(timeout=0.5)
            if process.is_alive():
                process.kill()
                process.join(timeout=0.5)
            self._discard_child()

    def _discard_child(self) -> None:
        process = self._process
        if process is not None and not process.is_alive():
            process.join(timeout=0.1)
        for channel in (self._commands, self._responses):
            if channel is not None:
                with contextlib.suppress(OSError, ValueError):
                    channel.close()
        self._process = None
        self._commands = None
        self._responses = None
        self._loaded = False

    def _drain_state_messages(self) -> None:
        with self._state_lock:
            responses = self._responses
        if responses is None:
            return
        while True:
            try:
                message = responses.get_nowait()
            except queue.Empty:
                return
            self._handle_state_message(message)

    def _handle_state_message(self, message) -> None:
        name = message[0]
        callback = None
        with self._state_lock:
            if name == "loaded":
                self._loaded = True
                self._load_error = None
                self._ready.set()
                callback = self._on_loaded
            elif name == "unloaded":
                self._loaded = False
                callback = self._on_unloaded
            elif name == "load_error":
                self._loaded = False
                self._load_error = ASRProcessError(f"{message[1]}: {message[2]}")
                self._ready.set()
        if callback is not None:
            try:
                callback()
            except Exception as exc:
                log.error("ASR model-state callback failed: %s", exc)

    def _fail_process_jobs(self, exc: BaseException) -> None:
        active = self._active
        if active is not None and not active.future.done():
            active.future.set_exception(exc)
        while True:
            try:
                _rank, _sequence, job = self._jobs.get_nowait()
            except queue.Empty:
                break
            if job is not None and not job.future.done():
                job.future.set_exception(exc)

    def _forward_logs(self) -> None:
        while True:
            record = self._log_records.get()
            if record is None:
                return
            target = logging.getLogger(record.name)
            if target.isEnabledFor(record.levelno):
                target.handle(record)
