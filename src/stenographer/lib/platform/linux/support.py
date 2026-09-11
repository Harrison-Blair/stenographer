# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import signal


def signal_reason(signum: int) -> str:
    """Name a stop signal for the core's log line. PURE.

    Runs inside a signal handler, so it stays allocation-light (the enum
    lookup returns an interned name) and never raises: an unrecognized number
    — a signal this build's ``signal.Signals`` does not know — degrades to a
    numeric label so ``request_stop`` still fires behind it.
    """

    try:
        return signal.Signals(signum).name
    except Exception:
        return f"signal {signum}"
