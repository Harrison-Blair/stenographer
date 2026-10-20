# SPDX-License-Identifier: GPL-3.0-or-later
"""Render live session panels and transcript layouts for the hub."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stenographer.lib.live.live_session import LiveSession


def render_live_view(
    session: LiveSession | None,
    *,
    model_name: str,
    mic_device: str,
    cpu_percent: float | None,
    split: bool,
) -> str:
    """Return the Live section text for an active or idle session."""
    paused = session is not None and session.paused
    state = "PAUSED" if paused else "REC" if session is not None else "STOPPED"
    elapsed = session.elapsed_seconds if session is not None else 0
    queue_depth = session.queue_depth if session is not None else 0
    failed_count = session.failed_phrase_count if session is not None else 0
    model = session.model_name if session is not None else model_name
    cpu = "—" if cpu_percent is None else f"{cpu_percent:.0f}%"

    parts = [
        "┌─ engine ───────────────────────────────────────────────",
        f"│ model {model}",
        f"│ queue {queue_depth} · failed {failed_count} · CPU {cpu}",
        "└────────────────────────────────────────────────────────",
        "┌─ REC ───────────────────────────────────────────────────",
        f"│ {state} · {format_time(elapsed)}",
        "└────────────────────────────────────────────────────────",
    ]
    for key, source, device in (
        ("m", "mic", mic_device),
        ("s", "system", "Default output monitor"),
    ):
        source_state = session.source_states[source] if session is not None else "off"
        level = session.levels_dbfs[source] if session is not None else float("-inf")
        floor = session.meter_floor_dbfs if session is not None else -70.0
        reason = session.source_reasons[source] if session is not None else None
        level_text = "-inf" if not math.isfinite(level) else f"{level:.0f}"
        detail = f"│ [{key}] {source.upper()} {source_state.upper()} · {device}"
        if reason:
            detail += f" ({reason})"
        parts.extend(
            (
                f"┌─ {source.upper()} ─────────────────────────────────────────────",
                detail,
                f"│ {format_meter(level, floor)} · {level_text} dBFS",
                "└────────────────────────────────────────────────────────",
            )
        )

    lines = session.lines if session is not None else ()
    speakers = session.speakers if session is not None else ()
    count = len(speakers)
    speaker_label = "speaker" if count == 1 else "speakers"
    view = "split" if split else "mixed"
    parts.append(f"transcript · {view} · {count} {speaker_label}")
    if split:
        parts.append("time      | MIC                                | SYSTEM")
        for line in sorted(lines, key=lambda item: item.start):
            cell = f"[{line.label}] {line.text}"
            mic = cell if line.source == "mic" else ""
            system = cell if line.source == "system" else ""
            parts.append(f"{format_time(line.start)} | {mic:<34} | {system}")
    else:
        for line in sorted(lines, key=lambda item: item.start):
            parts.append(f"{format_time(line.start)}  [{line.label}]  {line.text}")
    if session is None:
        parts.append("Press space to start recording.")
    return "\n".join(parts)


def format_meter(level_dbfs: float, floor_dbfs: float = -70.0) -> str:
    """Map a level from the configured floor to the meter maximum."""
    filled = (
        0
        if not math.isfinite(level_dbfs)
        else min(5, max(0, int((level_dbfs - floor_dbfs) / (-10.0 - floor_dbfs) * 5)))
    )
    return "█" * filled + "·" * (5 - filled)


def read_cpu_percent() -> float:
    """Read host CPU utilization without waiting for another sample."""
    import psutil

    return psutil.cpu_percent(interval=None)


def format_time(seconds: float | int) -> str:
    """Format an elapsed time as hours, minutes, and seconds."""
    whole_seconds = max(0, int(seconds))
    hours, remainder = divmod(whole_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
