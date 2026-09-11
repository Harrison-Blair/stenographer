# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import contextlib
import logging
import multiprocessing
import queue
from typing import TYPE_CHECKING

from stenographer.lib.logging.pipeline import (
    start_worker_log_relay,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from stenographer.lib.config.models import AsrConfig

from stenographer.lib.platform.asr import _JOIN_SECONDS, _child_main


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
