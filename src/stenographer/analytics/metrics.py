# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure analytics definitions. Durations end in _s or _ms; memory uses bytes.

Words are Unicode alphanumeric runs, allowing internal apostrophes. Hyphenated
words count separately; punctuation alone does not count. Headline audio is
sample-based input duration attached to accepted ASR results (including empty
results), never wall time or VAD speech estimates. Missing values stay unknown.
New stop_to_ready_ms measurements end at successful formatting, before delivery;
older persisted values retain their historical semantics without rewriting.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

_WORD = re.compile(r"[^\W_]+(?:['\u2019][^\W_]+)*", re.UNICODE)
METRICS = frozenset(
    [
        "round_trip_ms",
        "finalize_ms",
        "input_rate",
        "recovered",
        "mean_rms",
        "words",
        "recognized_words",
        "final_words",
        "copied_words",
        "chord_words",
        "asr_audio_s",
        "capture_s",
        "vad_s",
        "activate_ms",
        "press_to_callback_ms",
        "activation_to_callback_ms",
        "capture_finalize_ms",
        "load_ms",
        "decode_ms",
        "inference_ms",
        "worker_roundtrip_ms",
        "format_ms",
        "copy_ms",
        "release_wait_ms",
        "stop_to_ready_ms",
        "stop_to_chord_ms",
        "total_ms",
        "lock_wait_ms",
        "in_frames",
        "out_frames",
        "sample_rate",
        "output_rate",
        "channels",
        "resampled",
        "capped",
        "overflow",
        "overflow_count",
        "recovery",
        "callback_count",
        "callback_timing_count",
        "callback_metadata_dropped",
        "max_adc_gap_ms",
        "adc_discontinuities",
        "peak_rms",
        "rms",
        "peak_amplitude",
        "clipped_samples",
        "clipping_fraction",
        "frames_above",
        "vad_frames",
        "segments",
        "chars_raw",
        "chars_out",
        "cold",
        "release_timeout",
        "ignored_busy_presses",
        "app_cpu_s",
        "app_rss_bytes_max",
        "host_cpu_percent_avg",
        "host_memory_used_bytes_max",
        "gpu_utilization_percent_avg",
        "gpu_memory_used_bytes_max",
        "resource_window_s",
        "resource_boundary_samples",
        "resource_boundary_missing",
        "resource_samples",
        "resource_expected_samples",
        "resource_coverage",
        "resource_probe_failures",
        "app_cpu_samples",
        "app_memory_samples",
        "host_cpu_samples",
        "host_memory_samples",
        "gpu_utilization_samples",
        "gpu_memory_samples",
    ]
)
CONTEXT_KEYS = frozenset(
    [
        "app_version",
        "model",
        "model_version",
        "runtime_version",
        "os_version",
        "python_version",
        "compute_type",
        "cpu_threads",
        "os",
        "architecture",
        "device",
        "sample_rate",
        "channels",
        "mode",
        "resource_availability",
    ]
)
PHASES = (
    "accepted_start",
    "secured_capture",
    "accepted_recognition",
    "clipboard_confirmed",
    "terminal",
)
OUTCOMES = frozenset(
    [
        "success",
        "delivered",
        "empty",
        "gate_rejected",
        "start_failed",
        "stop_failed",
        "model_failed",
        "decode_failed",
        "timeout",
        "crashed",
        "pathological",
        "cancelled",
        "copy_failed",
        "chord_failed",
        "interrupted",
        "error",
    ]
)


def count_words(text: str) -> int:
    return len(_WORD.findall(text))


def clean_metrics(values: Mapping[str, object]) -> dict[str, int | float | bool]:
    """Reject unrecognized fields and nonfinite/negative measurements before persistence."""
    result: dict[str, int | float | bool] = {}
    for key, value in values.items():
        if key not in METRICS:
            raise ValueError(f"Unknown analytics metric: {key}")
        if value is None:
            continue
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"Invalid analytics metric: {key}")
        result[key] = value
    return result


def clean_context(values: Mapping[str, object]) -> dict[str, str | int | float | bool]:
    result: dict[str, str | int | float | bool] = {}
    for key, value in values.items():
        if key not in CONTEXT_KEYS:
            raise ValueError(f"Unknown analytics context: {key}")
        if value is None:
            continue
        if not isinstance(value, (str, int, float, bool)):
            raise ValueError(f"Invalid analytics context: {key}")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"Invalid analytics context: {key}")
        if isinstance(value, str) and (len(value) > 256 or any(ord(c) < 32 for c in value)):
            raise ValueError(f"Invalid analytics context: {key}")
        result[key] = value
    return result


def distribution(values: Sequence[int | float | None]) -> dict[str, int | float | None]:
    known = sorted(float(value) for value in values if value is not None)
    count = len(known)
    return {
        "count": count,
        "missing": len(values) - count,
        "average": sum(known) / count if count else None,
        "p95": known[math.ceil(count * 0.95) - 1] if count else None,
        "p99": known[math.ceil(count * 0.99) - 1] if count else None,
    }


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def local_date_bound(value: str, *, end: bool = False) -> str:
    """Local calendar day to UTC; end bounds are exclusive next-day midnight."""
    day = date.fromisoformat(value)
    if end:
        day += timedelta(days=1)
    return datetime.combine(day, time.min).astimezone(UTC).isoformat(timespec="microseconds")


def summarize(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    totals = {
        name: sum(record["metrics"].get(name, 0) for record in records)
        for name in (
            "recognized_words",
            "final_words",
            "copied_words",
            "chord_words",
            "asr_audio_s",
            "capture_s",
            "vad_s",
            "ignored_busy_presses",
        )
    }
    days: dict[str, dict[str, int | float]] = {}
    for record in records:
        day = datetime.fromisoformat(record["started_at"]).astimezone().date().isoformat()
        point = days.setdefault(day, {"utterances": 0, "recognized_words": 0, "asr_audio_s": 0})
        point["utterances"] += 1
        for key in ("recognized_words", "asr_audio_s"):
            point[key] += record["metrics"].get(key, 0)
    totals.update(
        utterances=len(records),
        active_days=len(days),
        incomplete=sum(record["outcome"] is None for record in records),
    )
    return {
        "totals": totals,
        "metrics": {
            key: distribution([record["metrics"].get(key) for record in records])
            for key in sorted(METRICS)
        },
        "daily": [{"date": day, **days[day]} for day in sorted(days)],
        "outcomes": dict(Counter(record["outcome"] or "incomplete" for record in records)),
    }
