# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import shlex
import signal

_APP = "stenographer"


def _run_with_config(path: str) -> str:
    return f"STENOGRAPHER_CONFIG={shlex.quote(path)} stenographer run"


def signal_reason(signum: int) -> str:
    """Name a stop signal without risking failure in stop context."""

    try:
        return signal.Signals(signum).name
    except Exception:
        return f"signal {signum}"
