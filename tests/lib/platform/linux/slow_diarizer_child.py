# SPDX-License-Identifier: GPL-3.0-or-later
"""Stand-in speaker helpers with the real message protocol and no native library."""

from __future__ import annotations

import time

SLOW_PUSH_SECONDS = 0.02


def _serve(commands, results, push_seconds: float) -> None:
    results.send(("ready",))
    while True:
        try:
            message = commands.recv()
        except EOFError:
            return
        kind, sid = message[0], message[1]
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


def quick_child(commands, results, threads: int) -> None:
    _serve(commands, results, 0.0)
