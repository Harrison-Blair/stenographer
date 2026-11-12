# SPDX-License-Identifier: GPL-3.0-or-later
"""ASR process and transport doubles."""

import queue

from stenographer.lib.transcribe.results import TranscriptionResult


class FakeAsrProcess:
    """One ASR child as a pair of real queues, a pid, and a liveness flag.

    It is the ``AsrProcess`` the transport hands back; the parent-side policy
    under test never learns whether a real process is behind it. Real process
    lifecycle stays in the smoke suite.
    """

    def __init__(self, *, pid: int = 4321, reply=None, timeouts: int = 0) -> None:
        self.pid = pid
        self.exit_code: int | None = None
        self.running = True
        self.sent: list[tuple] = []
        self.closes: list[bool] = []
        self.receives = 0
        self.timeouts = timeouts
        self._reply = reply if reply is not None else _reply_normally
        self._responses: queue.Queue = queue.Queue()

    def is_running(self) -> bool:
        return self.running

    def send(self, message: tuple) -> None:
        self.sent.append(message)
        response = self._reply(self, message)
        if response is not None:
            self._responses.put(response)

    def receive(self, timeout: float):
        self.receives += 1
        if self.timeouts > 0:
            self.timeouts -= 1
            raise TimeoutError("no response yet")
        try:
            return self._responses.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError("no response yet") from None

    def close(self, graceful: bool = False) -> None:
        self.closes.append(graceful)
        self.running = False


class FakeAsrTransport:
    """Hands out prepared children instead of spawning real ones."""

    def __init__(self, *children, error: Exception | None = None) -> None:
        self.pending = list(children)
        self.error = error
        self.spawned: list[FakeAsrProcess] = []
        self.log_sinks: list[object] = []

    def spawn(self, *, on_log):
        if self.error is not None:
            raise self.error
        child = self.pending.pop(0) if self.pending else FakeAsrProcess()
        self.spawned.append(child)
        self.log_sinks.append(on_log)
        return child


def _result(text: str = "hello there") -> TranscriptionResult:
    return TranscriptionResult(text=text, duration_seconds=1.0, segments=[], inference_ms=12.5)


def _reply_normally(process: FakeAsrProcess, message: tuple):
    if message[0] == "load":
        return ("model_ready",)
    if message[0] == "job":
        return ("ok", _result())
    return None
