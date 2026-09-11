# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import os
from pathlib import Path

from stenographer.lib.logging.pipeline import fmt_event
from stenographer.overlay.entry import OVERLAY_ENTRY_ARG
from stenographer.overlay.logging.pipeline import cap_helper_log, helper_log_path
from stenographer.overlay.supervision.constants import (
    _POLL_SECONDS,
    _READY_TIMEOUT_SECONDS,
    _SPECTRUM_INTERVAL,
    log,
)


def helper_command(executable: str, *, frozen: bool) -> tuple[str, ...]:
    """Return the private helper re-exec command without inspecting process state."""
    if frozen:
        return executable, OVERLAY_ENTRY_ARG
    return executable, "-m", "stenographer.cli", OVERLAY_ENTRY_ARG


def helper_ready_timed_out(
    *, started_at: float, now: float, ready: bool, timeout: float = _READY_TIMEOUT_SECONDS
) -> bool:
    """Pure readiness deadline policy for a started helper process."""
    return not ready and now - started_at >= timeout


def schedule_spectrum(
    recording: bool, next_spectrum_at: float | None, now: float
) -> tuple[float | None, bool]:
    """Return (new_deadline, run_produce). Cadence only while recording;
    exactly one cleanup produce on leaving recording."""
    if not recording:
        return None, next_spectrum_at is not None
    if next_spectrum_at is None or now >= next_spectrum_at:
        return now + _SPECTRUM_INTERVAL, True
    return next_spectrum_at, False


def serve_timeout(
    now: float, next_spectrum_at: float | None, poll_seconds: float = _POLL_SECONDS
) -> float:
    if next_spectrum_at is None:
        return poll_seconds
    return min(poll_seconds, max(0.0, next_spectrum_at - now))


def _helper_stderr_path() -> Path | None:
    """The file a spawned helper's stderr appends to, capped before it is opened.

    The parent caps it so the child, which caps the same path before installing
    its own handler, finds it already small and leaves the inode alone — one
    file, two append-mode descriptors, and no rotation while either is open.
    """
    try:
        path = helper_log_path(os.environ, Path.home())
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.debug(fmt_event("overlay", "helper_log_unavailable", error=type(exc).__name__))
        return None
    cap_helper_log(path)
    return path
