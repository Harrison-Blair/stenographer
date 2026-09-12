# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure hotkey admission, edge mapping, and pipeline outcome policy."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Literal

from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.lib.daemon.outcome import Outcome

if TYPE_CHECKING:
    from collections.abc import Callable

    from stenographer.lib.daemon.daemon import Daemon


def _ignore_edge() -> None:
    """Falling-edge sink for toggle mode: only presses drive the session."""


def edge_handlers(daemon: Daemon, mode: str) -> tuple[Callable[[], None], Callable[[], None]]:
    """Map ``hotkey.mode`` onto the (rising, falling) edge callbacks.

    In toggle mode only presses drive the session, so the falling edge is inert;
    hybrid shares that press and gives the falling edge to ``on_hybrid_release``,
    which decides latch vs stop.
    PURE given *daemon*: it reads no config and touches no platform surface.
    """
    if mode == "toggle":
        return daemon.on_toggle_press, _ignore_edge
    if mode == "hybrid":
        return daemon.on_toggle_press, daemon.on_hybrid_release
    return daemon.on_key_down, daemon.on_key_up


def classify_pipeline(
    *, gate_passed: bool, transcript_nonempty: bool, deliver_result: bool | None
) -> tuple[Outcome, str | None]:
    """Map a pipeline run to its outcome and optional error message. PURE.

    A failed energy gate or an empty transcript is success-shaped — no paste, no
    error cue. Otherwise the delivery result decides: a False deliver on
    non-empty text is an error (deliver already withheld the chord on copy
    failure), never treated as silent.
    """
    if not gate_passed:
        return (Outcome.SILENT, None)
    if not transcript_nonempty:
        return (Outcome.SILENT, None)
    if deliver_result:
        return (Outcome.DELIVERED, None)
    return (Outcome.ERROR, "could not copy transcript to clipboard")


def can_start(recording: bool, busy: bool, stopping: bool) -> bool:
    """Admit a new utterance only when idle — one utterance at a time. PURE."""
    return not (recording or busy or stopping)


def ignored_edge_reason(recording: bool, busy: bool, stopping: bool) -> str:
    """Name why an edge was refused, most specific state first. PURE.

    "recording_or_busy" was true of every refusal and therefore explained none
    of them; a press that vanished during shutdown looked exactly like one that
    vanished mid-decode.
    """
    if recording:
        return "recording"
    if busy:
        return "busy"
    if stopping:
        return "stopping"
    return "none"


def toggle_action(
    *, recording: bool, busy: bool, stopping: bool
) -> Literal["start", "stop"] | None:
    """Map a toggle- or hybrid-mode press edge to a session action. PURE.

    A press while recording always stops — even during shutdown, so a live
    capture is never stranded. Otherwise it starts only when fully idle
    (``can_start``); a press during transcription neither starts nor queues.
    """
    if recording:
        return "stop"
    if can_start(recording, busy, stopping):
        return "start"
    return None


def hybrid_release_action(*, held_seconds: float, threshold: float) -> Literal["stop", "latch"]:
    """Map a hybrid-mode release to a session action. PURE.

    A press held to the threshold is a hold and stops on release; anything
    shorter is a tap, and the recording stays latched until the next press.
    """
    return "stop" if held_seconds >= threshold else "latch"


def max_duration_applies(armed_generation: int, current_generation: int, recording: bool) -> bool:
    """Guard a fired max-duration timer against stale delivery. PURE.

    ``Timer.cancel()`` cannot stop a callback that already fired and is
    blocked on the state lock, so a timer armed for recording N could
    otherwise stop recording N+1. The timer only applies to the very
    recording it was armed for, and only while that recording is live.
    """
    return armed_generation == current_generation and recording


def cancel_action(*, recording: bool, busy: bool) -> Literal["recording", "pipeline"] | None:
    """Select the active utterance stage that a cancel edge should stop. PURE."""
    if recording:
        return "recording"
    if busy:
        return "pipeline"
    return None


def cancel_state(*, shutting_down: bool) -> OverlayState:
    """Choose the terminal display state for a cancellation. PURE."""
    return OverlayState.HIDDEN if shutting_down else OverlayState.CANCELLED


def remaining_seconds(deadline: float) -> float:
    """What is left of a ``time.perf_counter()`` deadline, never negative.

    Not PURE in the sense the rest of this module is — it reads the clock —
    but it is still a small, deterministic-given-the-clock calculation with
    no config or platform dependency, so it lives here rather than as a
    method on ``Daemon``. Used by ``Daemon.stop()`` to give every bounded
    shutdown wait a share of one deadline rather than a fresh budget each.
    The clamp keeps a deadline already in the past well-defined: it becomes
    an immediate, zero-length ``join`` rather than a negative timeout.
    """
    return max(0.0, deadline - time.perf_counter())
