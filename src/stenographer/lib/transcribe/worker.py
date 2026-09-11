# SPDX-License-Identifier: GPL-3.0-or-later
"""ASR child process: one request at a time, restart-if-dead, kill-on-idle.

Radically simplified by design: no job queue, no supersession, no
interim jobs. The parent is a blocking, synchronous handle that serialises
requests through a single lock; the child owns a lazily-built ``model.Model``
and accepts a load-only warm-up before decoding one utterance at a time. Child
death never takes the daemon down — it surfaces as a typed ``WorkerError`` and
respawns on the next request.

The pure policies live in ``worker_policy``; real process lifecycle is covered
by the smoke suite."""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

from stenographer.lib.logging.pipeline import (
    forward_worker_record,
    log_failure,
)
from stenographer.lib.transcribe.results import TranscriptionResult

if TYPE_CHECKING:
    from collections.abc import Callable

    import numpy as np

    from stenographer.lib.config.models import AsrConfig
    from stenographer.lib.platform.asr_process import AsrProcess
    from stenographer.lib.platform.asr_transport import AsrTransport

from stenographer.lib.transcribe.errors import (
    WorkerCrashedError,
    WorkerError,
    WorkerModelError,
    WorkerProtocolError,
    WorkerTimeoutError,
    _WorkerTimeoutError,
)
from stenographer.lib.transcribe.worker_event import WorkerEvent
from stenographer.lib.transcribe.worker_lifecycle import WorkerLifecycle
from stenographer.lib.transcribe.worker_policy import (
    _DECODE_MIN_TIMEOUT_SECONDS,
    _DECODE_REALTIME_MULTIPLIER,
    _POLL_SECONDS,
    decode_timeout_seconds,
    interpret_response,
    lifecycle_transition,
    response_poll_timeout,
    should_arm_idle_timer,
    should_teardown_for_response_error,
)
from stenographer.lib.transcribe.worker_timings import WorkerTimings

log = logging.getLogger(__name__)


_MODEL_LOAD_TIMEOUT_SECONDS = 120.0


class Worker:
    """Blocking parent-side handle. One outstanding request at a time, enforced
    structurally by holding ``_lock`` across warm-up and transcription."""

    def __init__(
        self,
        cfg: AsrConfig,
        *,
        transport: AsrTransport | None = None,
        on_model_loading: Callable[[], None] | None = None,
        on_model_ready: Callable[[], None] | None = None,
        on_model_loading_finished: Callable[[], None] | None = None,
        on_transcribing: Callable[[], None] | None = None,
    ) -> None:
        self._cfg = cfg
        self._on_model_loading = on_model_loading
        self._on_model_ready = on_model_ready
        self._on_model_loading_finished = on_model_loading_finished
        self._on_transcribing = on_transcribing
        self._idle_seconds = cfg.idle_unload_seconds
        self._lock = threading.RLock()
        self._transport = transport
        self._process: AsrProcess | None = None
        self._idle_timer: threading.Timer | None = None
        self._model_ready = threading.Event()
        self._model_hold = threading.Event()
        self._shutdown_requested = threading.Event()
        # One request at a time is structural here, so the last successful
        # transcription is unambiguously the caller's own.
        self.last_timings: WorkerTimings | None = None

    def hold_model(self) -> None:
        """Defer idle eviction until the current recording pipeline finishes."""
        self._model_hold.set()

    def release_model(self) -> None:
        """Release a recording hold and arm eviction when the worker is idle.

        This must never block on ``_lock``: callers hold the daemon lock, and
        the lock owner's lifecycle callbacks take that same daemon lock — a
        blocking acquire here would be an AB-BA deadlock. The lock owner is
        also not guaranteed to observe the cleared hold (it may already have
        evaluated its arming gate), so a failed acquire hands the arming to a
        short-lived helper thread that blocks safely, holding no daemon lock.
        """
        self._model_hold.clear()
        if not self._lock.acquire(blocking=False):
            threading.Thread(
                target=self._arm_idle_timer_deferred,
                name="stenographer-idle-arm",
                daemon=True,
            ).start()
            return
        try:
            self._restart_idle_timer()
        finally:
            self._lock.release()

    def _arm_idle_timer_deferred(self) -> None:
        # Runs on its own thread with no daemon lock held, so blocking is safe.
        # Redundant spawns are harmless: _restart_idle_timer cancels any
        # existing timer under the lock, and its gates keep the result correct.
        with self._lock:
            self._restart_idle_timer()

    def warmup(self, utterance: int | None = None) -> None:
        """Load the model without decoding audio.

        This is blocking by design; the daemon invokes it on its warm-up thread.
        A simultaneous ``transcribe`` waits on the same lock and reuses the
        loaded model, so a short recording cannot race a second model load.
        """
        with self._lock:
            self._begin_request()
            try:
                self._ensure_model_loaded(utterance)
            except WorkerError as exc:
                self._finish_response_error(exc)
                raise
            self._restart_idle_timer()

    def transcribe(self, samples: np.ndarray, utterance: int | None = None) -> TranscriptionResult:
        requested_at = time.perf_counter()
        self.last_timings = None
        with self._lock:
            # Measured inside the lock so it counts the wait a concurrent
            # warm-up imposed, which is the delay the caller actually felt.
            lock_wait_ms = (time.perf_counter() - requested_at) * 1000.0
            self.last_timings = WorkerTimings(lock_wait_ms, None, None)
            self._begin_request()
            load_started_at = time.perf_counter()
            try:
                loaded = self._ensure_model_loaded(utterance)
            except WorkerError as exc:
                self.last_timings = WorkerTimings(
                    lock_wait_ms, (time.perf_counter() - load_started_at) * 1000, None
                )
                self._finish_response_error(exc)
                if isinstance(exc, (WorkerTimeoutError, WorkerCrashedError)):
                    raise
                raise WorkerModelError("model loading failed") from exc
            load_ms = (time.perf_counter() - load_started_at) * 1000.0 if loaded else None
            self._abort_if_shutdown_requested("transcribe")
            self._emit_lifecycle((WorkerLifecycle.TRANSCRIBING,))
            decode_started_at = time.perf_counter()
            self._process.send(("job", samples, utterance))
            try:
                timeout_seconds = decode_timeout_seconds(
                    samples.shape[0],
                    minimum_seconds=_DECODE_MIN_TIMEOUT_SECONDS,
                    realtime_multiplier=_DECODE_REALTIME_MULTIPLIER,
                )
                interpreted = self._wait_for_response(
                    "transcribe", deadline=time.monotonic() + timeout_seconds
                )
                if isinstance(interpreted, WorkerEvent):
                    raise WorkerProtocolError("unexpected model-ready event during transcription")
            except WorkerError as exc:
                self.last_timings = WorkerTimings(
                    lock_wait_ms,
                    load_ms,
                    None,
                    round_trip_ms=(time.perf_counter() - decode_started_at) * 1000,
                )
                self._finish_response_error(exc)
                raise
            self.last_timings = WorkerTimings(
                lock_wait_ms=lock_wait_ms,
                load_ms=load_ms,
                decode_ms=interpreted.inference_ms,
                round_trip_ms=(time.perf_counter() - decode_started_at) * 1000.0,
            )
            self._restart_idle_timer()
            return interpreted

    def _begin_request(self) -> None:
        if self._shutdown_requested.is_set():
            raise WorkerError("ASR worker is shut down")
        self._cancel_timer()
        if self._process is None or not self._process.is_running():
            self._spawn()
        self._abort_if_shutdown_requested("request")

    def _ensure_model_loaded(self, utterance: int | None = None) -> bool:
        """Load the model if it is cold. True when this call did the loading."""
        if self._model_ready.is_set():
            return False
        self._emit_lifecycle(lifecycle_transition(model_loaded=False))
        try:
            self._process.send(("load", utterance))
            interpreted = self._wait_for_response(
                "model_load", deadline=time.monotonic() + _MODEL_LOAD_TIMEOUT_SECONDS
            )
            if interpreted is not WorkerEvent.MODEL_READY:
                raise WorkerProtocolError("worker result arrived before model-ready event")
            lifecycle = lifecycle_transition(model_loaded=False, event=interpreted)
            self._model_ready.set()
            self._emit_lifecycle(lifecycle)
            return True
        finally:
            # The optional observer is the source of display-only activity
            # metadata.  It must clear the border after both ready and error.
            self._emit_lifecycle((WorkerLifecycle.MODEL_LOADING_FINISHED,))

    def _wait_for_response(
        self, phase: str, *, deadline: float
    ) -> TranscriptionResult | WorkerEvent:
        while True:
            self._abort_if_shutdown_requested(phase)
            if not self._process.is_running():
                log.error(
                    "worker: child_exited phase=%s exit_code=%s",
                    phase,
                    self._process.exit_code,
                )
                self._teardown()
                raise WorkerCrashedError(f"ASR child exited during {phase}")
            poll_timeout = response_poll_timeout(
                now=time.monotonic(), deadline=deadline, poll_seconds=_POLL_SECONDS
            )
            if poll_timeout == 0:
                log.error("worker: request_timeout phase=%s", phase)
                raise _WorkerTimeoutError(f"ASR worker timed out during {phase}")
            try:
                message = self._process.receive(poll_timeout)
            except TimeoutError:
                continue
            self._abort_if_shutdown_requested(phase)
            return interpret_response(message)

    def _finish_response_error(self, exc: WorkerError) -> None:
        if should_teardown_for_response_error(exc):
            self._teardown()
        else:
            self._restart_idle_timer()

    def _abort_if_shutdown_requested(self, phase: str) -> None:
        """Abandon an in-flight request once lock-independent shutdown is set."""
        if not self._shutdown_requested.is_set():
            return
        log.info("worker: cancelling phase=%s reason=shutdown", phase)
        self._teardown()
        raise WorkerError(f"ASR worker shut down during {phase}")

    def _emit_lifecycle(self, events: tuple[WorkerLifecycle, ...]) -> None:
        callbacks = {
            WorkerLifecycle.MODEL_LOADING: self._on_model_loading,
            WorkerLifecycle.MODEL_READY: self._on_model_ready,
            WorkerLifecycle.MODEL_LOADING_FINISHED: self._on_model_loading_finished,
            WorkerLifecycle.TRANSCRIBING: self._on_transcribing,
        }
        for event in events:
            self._notify(callbacks[event], event.name.lower())

    @staticmethod
    def _notify(callback: Callable[[], None] | None, event: str) -> None:
        if callback is None:
            return
        try:
            callback()
        except Exception as exc:
            # Optional observers must never change transcription success.
            log_failure(
                log,
                logging.WARNING,
                "worker: lifecycle_callback_failed",
                exc,
                safe=True,
                lifecycle_event=event,
            )

    def is_alive(self) -> bool:
        proc = self._process
        return proc is not None and proc.is_running()

    @property
    def is_model_ready(self) -> bool:
        """Return whether the current live child has confirmed model readiness."""
        proc = self._process
        return self._model_ready.is_set() and proc is not None and proc.is_running()

    @property
    def process_ids(self) -> tuple[int, ...]:
        """Registered application children only; resource sampling never scans process names."""
        process = self._process
        return (process.pid,) if process is not None and process.pid is not None else ()

    def shutdown(self) -> None:
        """Idempotent, never raises. Ask the child to stop, then escalate."""
        # This must happen before taking ``_lock``: transcribe holds that lock
        # while polling, so the event is its lock-independent cancellation path.
        self._shutdown_requested.set()
        with self._lock:
            self._cancel_timer()
            self._teardown(graceful=True)

    def __enter__(self) -> Worker:
        return self

    def __exit__(self, *exc: object) -> None:
        self.shutdown()

    def _spawn(self) -> None:
        previous = self._process
        if previous is not None:
            log.warning(
                "worker: replacing_child phase=respawn exit_code=%s",
                previous.exit_code,
            )
        self._teardown()
        try:
            if self._transport is None:
                from stenographer.lib.platform import current_platform

                self._transport = current_platform().asr_transport()
            self._process = self._transport.spawn(self._cfg, on_log=forward_worker_record)
        except Exception as exc:
            log_failure(log, logging.ERROR, "worker: spawn_failed", exc, safe=True)
            self._teardown()
            raise WorkerError("could not start ASR child") from exc
        log.info("worker: spawned pid=%d", self._process.pid)

    def _idle_kill(self) -> None:
        # Acquires the same lock ``transcribe`` holds, so it can never fire
        # during an in-flight decode.
        with self._lock:
            self._idle_timer = None
            if self._model_hold.is_set():
                log.debug("worker: unload_deferred reason=recording")
                # Retry directly rather than via _restart_idle_timer: its hold
                # gate would make this a silent no-op, leaving the child
                # resident forever if no release ever arms a timer. The retry
                # deliberately bypasses the gate so a deferred unload
                # self-heals; a later successful arm cancels it anyway.
                self._idle_timer = threading.Timer(self._idle_seconds, self._idle_kill)
                self._idle_timer.daemon = True
                self._idle_timer.start()
                return
            log.info("worker: unload phase=idle")
            self._teardown()

    def _teardown(self, *, graceful: bool = False) -> None:
        proc, self._process = self._process, None
        self._model_ready.clear()
        if proc is not None:
            proc.close(graceful=graceful)

    def _restart_idle_timer(self) -> None:
        self._cancel_timer()
        if should_arm_idle_timer(
            idle_seconds=self._idle_seconds,
            hold_active=self._model_hold.is_set(),
            shutdown_requested=self._shutdown_requested.is_set(),
            process_alive=self._process is not None and self._process.is_running(),
        ):
            self._idle_timer = threading.Timer(self._idle_seconds, self._idle_kill)
            self._idle_timer.daemon = True
            self._idle_timer.start()

    def _cancel_timer(self) -> None:
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None
