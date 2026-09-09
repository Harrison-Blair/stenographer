# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared multiprocessing ASR transport. All providers resolve it lazily.

Owns native process/queue lifetime and the picklable child entry point. Tuple
messages, model policy and deadlines remain the core worker's responsibility.
"""

from __future__ import annotations

import contextlib
import logging
import multiprocessing
import queue
import time
from dataclasses import replace
from typing import TYPE_CHECKING

from stenographer.utils.logging_setup import (
    fmt_event,
    log_failure,
    set_utterance,
    start_worker_log_relay,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from stenographer.config import AsrConfig

log = logging.getLogger(__name__)
_JOIN_SECONDS = 2.0


class MultiprocessingAsrTransport:
    def spawn(
        self, config: AsrConfig, *, on_log: Callable[[logging.LogRecord], None]
    ) -> MultiprocessingAsrProcess:
        return MultiprocessingAsrProcess(config, on_log=on_log)


class MultiprocessingAsrProcess:
    def __init__(self, config: AsrConfig, *, on_log: Callable[[logging.LogRecord], None]) -> None:
        self._process = None
        self._request_q = None
        self._response_q = None
        self._log_q = None
        self._drain_logs = None
        self._closed = False
        self._pid: int | None = None
        self._exit_code: int | None = None
        try:
            ctx = multiprocessing.get_context("spawn")
            self._request_q = ctx.Queue()
            self._response_q = ctx.Queue()
            self._log_q = ctx.Queue()
            self._drain_logs = start_worker_log_relay(self._log_q, on_log=on_log)
            self._process = ctx.Process(
                target=_child_main,
                args=(config, self._request_q, self._response_q, self._log_q, logging.DEBUG),
                daemon=True,
            )
            self._process.start()
            self._pid = self._process.pid
        except BaseException:
            self.close()
            raise

    @property
    def pid(self) -> int | None:
        return self._pid

    @property
    def exit_code(self) -> int | None:
        return self._exit_code if self._closed else self._process.exitcode

    def is_running(self) -> bool:
        return not self._closed and self._process is not None and self._process.is_alive()

    def send(self, message: tuple[object, ...]) -> None:
        if self._closed:
            raise RuntimeError("ASR process is closed")
        self._request_q.put(message)

    def receive(self, timeout: float) -> object:
        if self._closed:
            raise RuntimeError("ASR process is closed")
        try:
            return self._response_q.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError("ASR response poll expired") from None

    def close(self, graceful: bool = False) -> None:
        if self._closed:
            return
        self._closed = True
        proc = self._process
        if proc is not None:
            with contextlib.suppress(Exception):
                if graceful and proc.is_alive():
                    self._request_q.put(("stop",))
                    proc.join(timeout=_JOIN_SECONDS)
                if proc.is_alive():
                    proc.terminate()
                    proc.join(timeout=_JOIN_SECONDS)
                if proc.is_alive():
                    proc.kill()
                    proc.join(timeout=_JOIN_SECONDS)
                self._exit_code = proc.exitcode
                proc.close()
        for channel in (self._request_q, self._response_q):
            if channel is not None:
                # A killed reader cannot drain queued audio. Do not leave its
                # feeder waiting during interpreter shutdown.
                with contextlib.suppress(Exception):
                    channel.cancel_join_thread()
                    channel.close()
        self._request_q = self._response_q = None
        if self._drain_logs is not None:
            with contextlib.suppress(Exception):
                self._drain_logs()
        self._drain_logs = None
        if self._log_q is not None:
            with contextlib.suppress(Exception):
                self._log_q.close()
                self._log_q.join_thread()
        self._log_q = None


def _child_main(cfg: AsrConfig, request_q, response_q, log_q, log_level: int) -> None:
    """Spawn entry (module-level, picklable). Load and decode one request at a
    time, staying healthy after a caught error. The model is built lazily on the
    first load request so the child inherits the local-cache-only load."""
    from stenographer.transcribe.model import Model
    from stenographer.transcribe.worker import classify_error, error_is_safe_to_render
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
            inference_started_at = time.perf_counter()
            result = model.transcribe(samples)
            result = replace(
                result, inference_ms=(time.perf_counter() - inference_started_at) * 1000
            )
        except Exception as exc:
            # Report and stay alive; native segfaults are handled by the parent
            # liveness poll, not here.
            log_failure(
                log,
                logging.ERROR,
                "asr: job_failed",
                exc,
                safe=error_is_safe_to_render(exc),
                phase=phase,
            )
            kind, detail = classify_error(exc)
            response_q.put(("error", kind, detail))
            continue
        response_q.put(("ok", result))
