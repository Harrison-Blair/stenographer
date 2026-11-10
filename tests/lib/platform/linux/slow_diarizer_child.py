# SPDX-License-Identifier: GPL-3.0-or-later
"""Stand-in speaker helpers with the real message protocol and no native library."""

from __future__ import annotations

import os
import time

SLOW_PUSH_SECONDS = 0.02
# A recording helper appends "KIND SID" for each command it receives to this file.
LOG_ENV = "STENOGRAPHER_TEST_HELPER_LOG"


def _serve(commands, results, push_seconds: float, log_path: str | None = None) -> None:
    log = open(log_path, "a", buffering=1) if log_path else None  # noqa: SIM115
    results.send(("ready",))
    while True:
        try:
            message = commands.recv()
        except EOFError:
            return
        kind, sid = message[0], message[1]
        if log is not None:
            log.write(f"{kind} {sid}\n")
        if kind == "open":
            results.send(("opened", sid))
        elif kind == "push":
            time.sleep(push_seconds)
            results.send(("pushed", sid))
        elif kind == "finish":
            results.send(("finished", sid, ()))


def slow_child(commands, results, threads: int) -> None:
    """Take SLOW_PUSH_SECONDS per push, far slower than real time for short pushes."""
    _serve(commands, results, SLOW_PUSH_SECONDS)


def recording_slow_child(commands, results, threads: int) -> None:
    """``slow_child`` that logs every command it receives to ``$LOG_ENV``."""
    _serve(commands, results, SLOW_PUSH_SECONDS, os.environ[LOG_ENV])


def quick_child(commands, results, threads: int) -> None:
    _serve(commands, results, 0.0)
