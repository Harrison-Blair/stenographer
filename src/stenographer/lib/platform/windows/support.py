# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import signal

_APP = "stenographer"


def _run_with_config(path: str) -> str:
    """``cmd.exe`` syntax for running the daemon against an explicit config path."""

    return f'set "STENOGRAPHER_CONFIG={path}" && stenographer run'


def signal_reason(signum: int) -> str:
    """Name a stop signal for the core's log line. PURE.

    Every stop reaching the stub arrives as a signal number; the console
    events ``SetConsoleCtrlHandler`` delivers (``CTRL_CLOSE_EVENT`` and
    friends) are *not* signal numbers and will be named by their own mapping
    when that handler lands — feeding one to ``signal.Signals`` would raise
    inside the host's stop callback. Hence the guard: an unnameable code
    degrades to a numeric label so ``request_stop`` still fires behind it.
    """

    try:
        return signal.Signals(signum).name
    except Exception:
        return f"signal {signum}"
