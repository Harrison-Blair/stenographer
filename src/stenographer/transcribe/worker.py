# SPDX-License-Identifier: GPL-3.0-or-later
"""ASR child process: one request at a time, restart-if-dead, kill-on-idle.

Radically simplified by design: no job queue, no supersession, no
interim jobs. The parent is a blocking, synchronous handle that serialises
requests through a single lock; the child owns a lazily-built ``model.Model``
and accepts a load-only warm-up before decoding one utterance at a time. Child
death never takes the daemon down — it surfaces as a typed ``WorkerError`` and
respawns on the next request.

The unit-testable surface is the pure policy helpers below; real process
lifecycle is covered by the smoke suite.
"""

from __future__ import annotations

import contextlib
import logging
import logging.handlers
import multiprocessing
import queue
import threading
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

from stenographer.constants import SAMPLE_RATE
from stenographer.transcribe.model import Model, PathologicalOutputError, TranscriptionResult
from stenographer.utils.logging_setup import fmt_event, log_failure, owned_handlers, set_utterance

if TYPE_CHECKING:
    from collections.abc import Callable

    import numpy as np

    from stenographer.config import AsrConfig

log = logging.getLogger(__name__)

_POLL_SECONDS = 0.1
_JOIN_SECONDS = 2.0
_MODEL_LOAD_TIMEOUT_SECONDS = 120.0
_DECODE_MIN_TIMEOUT_SECONDS = 60.0
_DECODE_REALTIME_MULTIPLIER = 4.0


class WorkerError(RuntimeError):
    """Any worker-surfaced failure: child crash, mid-request death, or a
    decode error round-tripped from the child."""


class WorkerPathologicalError(WorkerError):
    """The child rejected a degenerate decode. Surfaced distinctly so
    the daemon can discard rather than deliver; carries only the serialised
    detail string, since the original instance cannot cross the boundary."""


class WorkerProtocolError(WorkerError):
    """The child sent a malformed or out-of-order protocol response."""


class _WorkerTimeoutError(WorkerError):
    """An internal phase deadline expired while the child remained alive."""


@dataclass(frozen=True)
class WorkerTimings:
    """How one ``transcribe`` call spent its wall clock, in milliseconds.

    ``load_ms`` is ``None`` on a warm model, which is exactly the ``cold=0``
    case the utterance summary reports.
    """

    lock_wait_ms: float
    load_ms: float | None
    decode_ms: float


class WorkerEvent(Enum):
    """Metadata-only control events sent before a cold child's first decode."""

    MODEL_READY = auto()


class WorkerLifecycle(Enum):
    """Fixed observer signals emitted around model load and transcription."""

    MODEL_LOADING = auto()
    MODEL_READY = auto()
    MODEL_LOADING_FINISHED = auto()
    TRANSCRIBING = auto()


def lifecycle_transition(
    *, model_loaded: bool, event: WorkerEvent | None = None
) -> tuple[WorkerLifecycle, ...]:
    """Return the observer signals for a model-load boundary. PURE.

    A cold load first announces loading; the child's metadata-only ready event
    then announces readiness. The caller emits ``MODEL_LOADING_FINISHED`` after
    either readiness or failure. Warm-up and transcription share this transition,
    while ``TRANSCRIBING`` remains a separate signal emitted only immediately
    before a decode. A ready event after the model is already marked loaded is
    a protocol violation rather than a second lifecycle.
    """
    if event is None:
        return () if model_loaded else (WorkerLifecycle.MODEL_LOADING,)
    if event is WorkerEvent.MODEL_READY and not model_loaded:
        return (WorkerLifecycle.MODEL_READY,)
    raise WorkerProtocolError("unexpected model-ready worker event")


def should_arm_idle_timer(
    *,
    idle_seconds: float,
    hold_active: bool,
    shutdown_requested: bool,
    process_alive: bool,
) -> bool:
    """Whether an idle-eviction timer may be armed right now. PURE."""
    return idle_seconds > 0 and not hold_active and not shutdown_requested and process_alive


def should_teardown_for_response_error(exc: WorkerError) -> bool:
    """Malformed or timed-out protocol poisons the channel. PURE."""
    return isinstance(exc, (WorkerProtocolError, _WorkerTimeoutError))


def decode_timeout_seconds(
    sample_frames: int,
    *,
    sample_rate: int = SAMPLE_RATE,
    minimum_seconds: float = _DECODE_MIN_TIMEOUT_SECONDS,
    realtime_multiplier: float = _DECODE_REALTIME_MULTIPLIER,
) -> float:
    """Return the fixed decode deadline budget for 16 kHz audio. PURE."""
    return max(minimum_seconds, realtime_multiplier * sample_frames / sample_rate)


def response_poll_timeout(
    *, now: float, deadline: float, poll_seconds: float = _POLL_SECONDS
) -> float:
    """Clamp one queue poll to the remaining phase deadline. PURE."""
    return max(0.0, min(poll_seconds, deadline - now))


def classify_error(exc: Exception) -> tuple[str, str]:
    """Child-side: map an exception to a ``(kind, detail)`` tuple. The detail
    carries only exception metadata — never audio or transcript text."""
    if isinstance(exc, PathologicalOutputError):
        return ("pathological", str(exc))
    return ("inference", f"{type(exc).__name__}: {exc}")


def interpret_response(message: object) -> TranscriptionResult | WorkerEvent:
    """Parent-side: turn a child response tuple into a result or a typed raise.
    Malformed messages are described by SHAPE only, never by echoed payload."""
    if isinstance(message, tuple) and message:
        tag = message[0]
        if tag == "model_ready" and len(message) == 1:
            return WorkerEvent.MODEL_READY
        if tag == "ok" and len(message) == 2 and isinstance(message[1], TranscriptionResult):
            return message[1]
        if tag == "error" and len(message) == 3:
            if message[1] == "pathological" and isinstance(message[2], str):
                raise WorkerPathologicalError(message[2])
            if message[1] == "inference" and isinstance(message[2], str):
                raise WorkerError(message[2])
    raise WorkerProtocolError(f"malformed worker response of shape {_describe_shape(message)}")


def _describe_shape(message: object) -> str:
    if not isinstance(message, tuple):
        return type(message).__name__
    return f"({', '.join(type(el).__name__ for el in message)})"


def _child_main(cfg: AsrConfig, request_q, response_q, log_q, log_level: int) -> None:
    """Spawn entry (module-level, picklable). Load and decode one request at a
    time, staying healthy after a caught error. The model is built lazily on the
    first load request so the child inherits the local-cache-only load."""
    from stenographer.utils.logging_setup import configure_worker_logging

    configure_worker_logging(log_q, log_level)
    model = None
    while True:
        message = request_q.get()
        if message[0] == "stop":
            return
        # Every request carries the parent's utterance id so the child's own
        # ``asr:`` lines interleave with the daemon's under the same utt=N.
        set_utterance(message[-1])
        if message[0] == "load":
            try:
                if model is None:
                    model = Model(cfg)
            except Exception as exc:
                # A model-load failure names paths and library complaints, not
                # anything derived from audio: its text may be rendered.
                log_failure(
                    log, logging.ERROR, "asr: job_failed", exc, safe=True, phase="model_load"
                )
                kind, detail = classify_error(exc)
                response_q.put(("error", kind, detail))
                continue
            log.info(
                fmt_event(
                    "worker",
                    "child_started",
                    model=cfg.model,
                    compute_type=cfg.compute_type,
                    cpu_threads=model.cpu_threads,
                )
            )
            response_q.put(("model_ready",))
            continue

        phase = "decode"
        try:
            if model is None:
                raise RuntimeError("decode requested before model load")
            samples = message[1]
            result = model.transcribe(samples)
        except Exception as exc:
            # Report and stay alive; native segfaults are handled by the parent
            # liveness poll, not here.  safe=False: a decode failure is the one
            # lineage whose message can quote decoder output derived from the
            # audio, so only the class and the frames are ever rendered.
            log_failure(log, logging.ERROR, "asr: job_failed", exc, safe=False, phase=phase)
            kind, detail = classify_error(exc)
            response_q.put(("error", kind, detail))
            continue
        response_q.put(("ok", result))


class Worker:
    """Blocking parent-side handle. One outstanding request at a time, enforced
    structurally by holding ``_lock`` across warm-up and transcription."""

    def __init__(
        self,
        cfg: AsrConfig,
        *,
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
        self._ctx = multiprocessing.get_context("spawn")
        self._process: multiprocessing.process.BaseProcess | None = None
        self._request_q = None
        self._response_q = None
        self._log_q = None
        self._log_listener: logging.handlers.QueueListener | None = None
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
        with self._lock:
            # Measured inside the lock so it counts the wait a concurrent
            # warm-up imposed, which is the delay the caller actually felt.
            lock_wait_ms = (time.perf_counter() - requested_at) * 1000.0
            self._begin_request()
            load_started_at = time.perf_counter()
            try:
                loaded = self._ensure_model_loaded(utterance)
            except WorkerError as exc:
                self._finish_response_error(exc)
                raise
            load_ms = (time.perf_counter() - load_started_at) * 1000.0 if loaded else None
            self._abort_if_shutdown_requested("transcribe")
            self._emit_lifecycle((WorkerLifecycle.TRANSCRIBING,))
            decode_started_at = time.perf_counter()
            self._request_q.put(("job", samples, utterance))
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
                self._finish_response_error(exc)
                raise
            self.last_timings = WorkerTimings(
                lock_wait_ms=lock_wait_ms,
                load_ms=load_ms,
                decode_ms=(time.perf_counter() - decode_started_at) * 1000.0,
            )
            self._restart_idle_timer()
            return interpreted

    def _begin_request(self) -> None:
        if self._shutdown_requested.is_set():
            raise WorkerError("ASR worker is shut down")
        self._cancel_timer()
        if self._process is None or not self._process.is_alive():
            self._spawn()
        self._abort_if_shutdown_requested("request")

    def _ensure_model_loaded(self, utterance: int | None = None) -> bool:
        """Load the model if it is cold. True when this call did the loading."""
        if self._model_ready.is_set():
            return False
        self._emit_lifecycle(lifecycle_transition(model_loaded=False))
        try:
            self._request_q.put(("load", utterance))
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
            if not self._process.is_alive():
                log.error(
                    "worker: child_exited phase=%s exit_code=%s",
                    phase,
                    self._process.exitcode,
                )
                self._teardown()
                raise WorkerError(f"ASR child exited during {phase}")
            poll_timeout = response_poll_timeout(
                now=time.monotonic(), deadline=deadline, poll_seconds=_POLL_SECONDS
            )
            if poll_timeout == 0:
                log.error("worker: request_timeout phase=%s", phase)
                raise _WorkerTimeoutError(f"ASR worker timed out during {phase}")
            try:
                message = self._response_q.get(timeout=poll_timeout)
            except queue.Empty:
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
                event=event,
            )

    def is_alive(self) -> bool:
        proc = self._process
        return proc is not None and proc.is_alive()

    @property
    def is_model_ready(self) -> bool:
        """Return whether the current live child has confirmed model readiness."""
        proc = self._process
        return self._model_ready.is_set() and proc is not None and proc.is_alive()

    def shutdown(self) -> None:
        """Idempotent, never raises. Ask the child to stop, then escalate."""
        # This must happen before taking ``_lock``: transcribe holds that lock
        # while polling, so the event is its lock-independent cancellation path.
        self._shutdown_requested.set()
        with self._lock:
            self._cancel_timer()
            proc, request_q = self._process, self._request_q
            if proc is not None and request_q is not None:
                with contextlib.suppress(Exception):
                    if proc.is_alive():
                        request_q.put(("stop",))
                        proc.join(timeout=_JOIN_SECONDS)
            self._teardown()

    def __enter__(self) -> Worker:
        return self

    def __exit__(self, *exc: object) -> None:
        self.shutdown()

    def _spawn(self) -> None:
        previous = self._process
        if previous is not None:
            log.warning(
                "worker: replacing_child phase=respawn exit_code=%s",
                previous.exitcode,
            )
        self._teardown()
        self._request_q = self._ctx.Queue()
        self._response_q = self._ctx.Queue()
        self._log_q = self._ctx.Queue()
        # The parent's own handler is a queue forwarder, so fanning out to it
        # would enqueue the child's records a second time; the child's listener
        # targets the same real sinks the parent's listener owns.
        self._log_listener = logging.handlers.QueueListener(
            self._log_q,
            *owned_handlers(),
            respect_handler_level=True,
        )
        self._log_listener.start()
        self._process = self._ctx.Process(
            target=_child_main,
            args=(
                self._cfg,
                self._request_q,
                self._response_q,
                self._log_q,
                # The file sink is always DEBUG, so the child forwards everything.
                logging.DEBUG,
            ),
            daemon=True,
        )
        try:
            self._process.start()
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

    def _teardown(self) -> None:
        proc = self._process
        if proc is not None:
            with contextlib.suppress(Exception):
                if proc.is_alive():
                    proc.terminate()
                    proc.join(timeout=_JOIN_SECONDS)
                if proc.is_alive():
                    proc.kill()
                    proc.join(timeout=_JOIN_SECONDS)
        self._process = None
        self._model_ready.clear()
        for q in (self._request_q, self._response_q):
            if q is not None:
                with contextlib.suppress(Exception):
                    q.close()
        self._request_q = None
        self._response_q = None
        if self._log_listener is not None:
            with contextlib.suppress(Exception):
                self._log_listener.stop()
        self._log_listener = None
        if self._log_q is not None:
            with contextlib.suppress(Exception):
                self._log_q.close()
            with contextlib.suppress(Exception):
                self._log_q.join_thread()
        self._log_q = None

    def _restart_idle_timer(self) -> None:
        self._cancel_timer()
        if should_arm_idle_timer(
            idle_seconds=self._idle_seconds,
            hold_active=self._model_hold.is_set(),
            shutdown_requested=self._shutdown_requested.is_set(),
            process_alive=self._process is not None and self._process.is_alive(),
        ):
            self._idle_timer = threading.Timer(self._idle_seconds, self._idle_kill)
            self._idle_timer.daemon = True
            self._idle_timer.start()

    def _cancel_timer(self) -> None:
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None
