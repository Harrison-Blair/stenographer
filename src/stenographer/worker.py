# SPDX-License-Identifier: GPL-3.0-or-later
"""ASR child process: one request at a time, restart-if-dead, kill-on-idle.

Radically simplified per decision §2.10: no job queue, no supersession, no
interim jobs. The parent is a blocking, synchronous handle that serialises
requests through a single lock; the child owns a lazily-built ``model.Model``
and decodes one utterance at a time. Child death never takes the daemon down —
it surfaces as a typed ``WorkerError`` and respawns on the next request.

The whole unit-testable surface is the two pure helpers (``classify_error``,
``interpret_response``); real process lifecycle is covered by the smoke suite.
"""

from __future__ import annotations

import contextlib
import logging
import logging.handlers
import multiprocessing
import queue
import threading
from enum import Enum, auto
from typing import TYPE_CHECKING

from stenographer.model import Model, PathologicalOutputError, TranscriptionResult

if TYPE_CHECKING:
    from collections.abc import Callable

    import numpy as np

    from stenographer.config import AsrConfig

log = logging.getLogger(__name__)

_POLL_SECONDS = 0.1
_JOIN_SECONDS = 2.0


class WorkerError(RuntimeError):
    """Any worker-surfaced failure: child crash, mid-request death, or a
    decode error round-tripped from the child."""


class WorkerPathologicalError(WorkerError):
    """The child rejected a degenerate decode (§4.6). Surfaced distinctly so
    the daemon can discard rather than deliver; carries only the serialised
    detail string, since the original instance cannot cross the boundary."""


class WorkerProtocolError(WorkerError):
    """The child sent a malformed or out-of-order protocol response."""


class WorkerEvent(Enum):
    """Metadata-only control events sent before a cold child's first decode."""

    MODEL_READY = auto()


class WorkerLifecycle(Enum):
    """Fixed observer signals emitted around a worker request."""

    MODEL_LOADING = auto()
    MODEL_READY = auto()
    TRANSCRIBING = auto()


def lifecycle_transition(
    *, model_loaded: bool, event: WorkerEvent | None = None
) -> tuple[WorkerLifecycle, ...]:
    """Return the observer signals for a request boundary. PURE.

    A warm request starts transcribing immediately. A cold request first
    announces loading; the child's metadata-only ready event then announces
    ready followed by transcribing. A ready event after the model is already
    marked loaded is a protocol violation rather than a second lifecycle.
    """
    if event is None:
        if model_loaded:
            return (WorkerLifecycle.TRANSCRIBING,)
        return (WorkerLifecycle.MODEL_LOADING,)
    if event is WorkerEvent.MODEL_READY and not model_loaded:
        return (WorkerLifecycle.MODEL_READY, WorkerLifecycle.TRANSCRIBING)
    raise WorkerProtocolError("unexpected model-ready worker event")


def should_teardown_for_response_error(exc: WorkerError) -> bool:
    """Malformed protocol poisons the channel; inference errors do not. PURE."""
    return isinstance(exc, WorkerProtocolError)


def classify_error(exc: Exception) -> tuple[str, str]:
    """Child-side: map an exception to a ``(kind, detail)`` tuple. The detail
    carries only exception metadata — never audio or transcript text (§4.12)."""
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
    """Spawn entry (module-level, picklable). Decode one job at a time, staying
    healthy for the next request after a caught decode error. The model is built
    lazily on the first job so the child inherits local-cache-only load (§4.11)."""
    from stenographer.logging_setup import configure_worker_logging

    configure_worker_logging(log_q, log_level)
    model = None
    while True:
        message = request_q.get()
        if message[0] == "stop":
            return
        samples = message[1]
        phase = "model_load" if model is None else "decode"
        try:
            if model is None:
                model = Model(cfg)
                response_q.put(("model_ready",))
                phase = "decode"
            result = model.transcribe(samples)
        except Exception as exc:
            # Report and stay alive; native segfaults are handled by the parent
            # liveness poll, not here.
            log.error("asr: job failed phase=%s error_type=%s", phase, type(exc).__name__)
            kind, detail = classify_error(exc)
            response_q.put(("error", kind, detail))
            continue
        response_q.put(("ok", result))


class Worker:
    """Blocking parent-side handle. One outstanding request at a time, enforced
    structurally by holding ``_lock`` across the whole ``transcribe`` call."""

    def __init__(
        self,
        cfg: AsrConfig,
        *,
        on_model_loading: Callable[[], None] | None = None,
        on_model_ready: Callable[[], None] | None = None,
        on_transcribing: Callable[[], None] | None = None,
    ) -> None:
        self._cfg = cfg
        self._on_model_loading = on_model_loading
        self._on_model_ready = on_model_ready
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
        self._model_loaded = False

    def transcribe(self, samples: np.ndarray) -> TranscriptionResult:
        with self._lock:
            self._cancel_timer()
            if self._process is None or not self._process.is_alive():
                self._spawn()
            cold = not self._model_loaded
            self._emit_lifecycle(lifecycle_transition(model_loaded=self._model_loaded))
            self._request_q.put(("job", samples))
            while True:
                if not self._process.is_alive():
                    log.error(
                        "worker: child exited phase=transcribe exit_code=%s",
                        self._process.exitcode,
                    )
                    self._teardown()
                    raise WorkerError("ASR child exited during transcription")
                try:
                    message = self._response_q.get(timeout=_POLL_SECONDS)
                except queue.Empty:
                    continue
                try:
                    interpreted = interpret_response(message)
                    if interpreted is WorkerEvent.MODEL_READY:
                        lifecycle = lifecycle_transition(
                            model_loaded=self._model_loaded, event=interpreted
                        )
                        self._model_loaded = True
                        self._emit_lifecycle(lifecycle)
                        continue
                    if cold and not self._model_loaded:
                        raise WorkerProtocolError("worker result arrived before model-ready event")
                except WorkerError as exc:
                    if should_teardown_for_response_error(exc):
                        self._teardown()
                    else:
                        self._restart_idle_timer()
                    raise
                self._restart_idle_timer()
                return interpreted

    def _emit_lifecycle(self, events: tuple[WorkerLifecycle, ...]) -> None:
        callbacks = {
            WorkerLifecycle.MODEL_LOADING: self._on_model_loading,
            WorkerLifecycle.MODEL_READY: self._on_model_ready,
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
            log.warning(
                "worker: lifecycle callback failed event=%s error_type=%s",
                event,
                type(exc).__name__,
            )

    def is_alive(self) -> bool:
        proc = self._process
        return proc is not None and proc.is_alive()

    def shutdown(self) -> None:
        """Idempotent, never raises. Ask the child to stop, then escalate."""
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
                "worker: replacing child phase=respawn exit_code=%s",
                previous.exitcode,
            )
        self._teardown()
        self._request_q = self._ctx.Queue()
        self._response_q = self._ctx.Queue()
        self._log_q = self._ctx.Queue()
        parent_logger = logging.getLogger("stenographer")
        self._log_listener = logging.handlers.QueueListener(
            self._log_q,
            *parent_logger.handlers,
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
                parent_logger.getEffectiveLevel(),
            ),
            daemon=True,
        )
        try:
            self._process.start()
        except Exception as exc:
            log.error("worker: spawn failed error_type=%s", type(exc).__name__)
            self._teardown()
            raise
        self._model_loaded = False
        log.info("worker: spawned pid=%d", self._process.pid)

    def _idle_kill(self) -> None:
        # Acquires the same lock ``transcribe`` holds, so it can never fire
        # during an in-flight decode.
        with self._lock:
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
        self._model_loaded = False
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
        if self._idle_seconds > 0:
            self._idle_timer = threading.Timer(self._idle_seconds, self._idle_kill)
            self._idle_timer.daemon = True
            self._idle_timer.start()

    def _cancel_timer(self) -> None:
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None
