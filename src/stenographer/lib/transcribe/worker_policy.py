# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure inference-worker protocol and timeout policies."""

from __future__ import annotations

from stenographer.lib.audio.constants import SAMPLE_RATE
from stenographer.lib.transcribe.errors import (
    PathologicalOutputError,
    WorkerCrashedError,
    WorkerError,
    WorkerModelError,
    WorkerPathologicalError,
    WorkerProtocolError,
    WorkerTimeoutError,
)
from stenographer.lib.transcribe.results import TranscriptionResult

MODEL_READY = "model_ready"
"""What ``interpret_response`` returns for the child's metadata-only ready reply."""


_POLL_SECONDS = 0.1


_DECODE_MIN_TIMEOUT_SECONDS = 60.0


_DECODE_REALTIME_MULTIPLIER = 4.0


def classify_worker_failure(exc: WorkerError) -> str:
    """Project a typed worker failure into the fixed analytics vocabulary. PURE."""
    if isinstance(exc, WorkerPathologicalError):
        return "pathological"
    if isinstance(exc, WorkerTimeoutError):
        return "timeout"
    if isinstance(exc, WorkerCrashedError):
        return "crashed"
    if isinstance(exc, WorkerModelError):
        return "model_failed"
    return "decode_failed"


def should_arm_idle_timer(
    *,
    idle_seconds: float,
    hold_active: bool,
    shutdown_requested: bool,
    process_alive: bool,
) -> bool:
    """Whether an idle-eviction timer may be armed right now. PURE."""
    return idle_seconds > 0 and not hold_active and not shutdown_requested and process_alive


def should_teardown_for_response_error(exc: WorkerError) -> bool:
    """Malformed or timed-out protocol poisons the channel. PURE."""
    return isinstance(exc, (WorkerProtocolError, WorkerTimeoutError))


def decode_timeout_seconds(sample_frames: int) -> float:
    """Return the fixed decode deadline budget for 16 kHz audio. PURE."""
    return max(
        _DECODE_MIN_TIMEOUT_SECONDS, _DECODE_REALTIME_MULTIPLIER * sample_frames / SAMPLE_RATE
    )


def response_poll_timeout(*, now: float, deadline: float) -> float:
    """Clamp one queue poll to the remaining phase deadline. PURE."""
    return max(0.0, min(_POLL_SECONDS, deadline - now))


def classify_error(exc: Exception) -> tuple[str, str]:
    """Child-side: map an exception to a ``(kind, detail)`` tuple. The detail
    carries only exception metadata — never audio or transcript text."""
    if isinstance(exc, PathologicalOutputError):
        return ("pathological", str(exc))
    return ("inference", f"{type(exc).__name__}: {exc}")


def error_is_safe_to_render(exc: Exception) -> bool:
    """Whether a decode failure's own message may be logged verbatim. PURE.

    Only ``PathologicalOutputError``'s is: it is audited to carry counts
    ("word density exceeded limit (312 > 40)") and is the whole account of a
    decode the daemon then discards. Every other decode failure comes from the
    inference stack, whose message can quote output derived from the audio.
    """
    return isinstance(exc, PathologicalOutputError)


def interpret_response(message: object) -> TranscriptionResult | str:
    """Parent-side: turn a child response tuple into a result or a typed raise.
    Malformed messages are described by SHAPE only, never by echoed payload."""
    if isinstance(message, tuple) and message:
        tag = message[0]
        if tag == "model_ready" and len(message) == 1:
            return MODEL_READY
        if tag == "ok" and len(message) == 2 and isinstance(message[1], TranscriptionResult):
            return message[1]
        if tag == "error" and len(message) == 3:
            if message[1] == "pathological" and isinstance(message[2], str):
                raise WorkerPathologicalError(message[2])
            if message[1] == "inference" and isinstance(message[2], str):
                raise WorkerError(message[2])
    raise WorkerProtocolError(f"malformed worker response of shape {_describe_shape(message)}")


def _describe_shape(message: object) -> str:
    if not isinstance(message, tuple):
        return type(message).__name__
    return f"({', '.join(type(el).__name__ for el in message)})"
