#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Repository-only synthetic analytics overhead comparison; never records microphone audio.

Run with .venv/bin/python scripts/analytics_overhead.py. Each comparison uses an
isolated temporary database, never personal history. This measures checkpoint
producer and background persistence/probe cost, not capture or ASR regressions.
"""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from stenographer.analytics import AnalyticsSession, Store
from stenographer.platform import current_platform


def compare(
    *,
    utterances: int = 60,
    repeats: int = 2,
    pause_s: float = 0.005,
    active_seconds: float = 0,
) -> dict:
    if utterances < 1 or repeats < 1 or pause_s < 0 or active_seconds < 0:
        raise ValueError("Utterances/repeats must be positive; pause must be nonnegative")
    results = []
    for repetition in range(repeats):
        for profiling in (False, True):
            with tempfile.TemporaryDirectory(
                prefix="stenographer-analytics-overhead-"
            ) as directory:
                path = Path(directory) / "analytics.db"
                probe = current_platform().resource_probe() if profiling else None
                session = AnalyticsSession(
                    path,
                    resource_probe=probe,
                    queue_size=max(128, utterances * 4),
                )
                samples = []
                cpu_start = time.process_time()
                wall_start = time.perf_counter()
                for identity in range(utterances):
                    started = time.perf_counter()
                    session.start(identity)
                    start_cost = time.perf_counter() - started
                    if active_seconds:
                        time.sleep(active_seconds)
                    started = time.perf_counter()
                    session.checkpoint(identity, "secured_capture", {"capture_s": 2.0})
                    session.checkpoint(
                        identity,
                        "accepted_recognition",
                        {
                            "recognized_words": 10,
                            "asr_audio_s": 2.0,
                        },
                    )
                    session.finish(identity, "success")
                    samples.append((time.perf_counter() - started + start_cost) * 1000)
                    time.sleep(pause_s)
                drained = session.close(timeout=60)
                cpu_s = time.process_time() - cpu_start
                elapsed_s = time.perf_counter() - wall_start
                report = Store(path).report()
                rows = Store(path).records()
                results.append(
                    {
                        "repetition": repetition + 1,
                        "profiling": profiling,
                        "operations": utterances * 4,
                        "enqueue_four_checkpoints_ms_median": statistics.median(samples),
                        "enqueue_four_checkpoints_ms_p95": sorted(samples)[
                            max(0, (95 * utterances + 99) // 100 - 1)
                        ],
                        "cpu_s": cpu_s,
                        "elapsed_s": elapsed_s,
                        "drained": drained,
                        "health": session.health,
                        "utterances": report["totals"]["utterances"],
                        "resource_samples": sum(
                            row["metrics"].get("resource_samples", 0) for row in rows
                        ),
                        "resource_boundary_missing": sum(
                            row["metrics"].get("resource_boundary_missing", 0) for row in rows
                        ),
                        "resource_coverage_average": report["metrics"]["resource_coverage"][
                            "average"
                        ],
                        "utterances_without_resource_samples": sum(
                            not row["metrics"].get("resource_samples", 0) for row in rows
                        ),
                    }
                )
                if not drained:
                    raise RuntimeError("Synthetic writer did not drain within its timeout")
    return {
        "measured_at": datetime.now(UTC).isoformat(),
        "method": {
            "utterances": utterances,
            "repeats": repeats,
            "producer_pause_s": pause_s,
            "active_seconds_per_utterance": active_seconds,
            "checkpoints_per_utterance": 4,
            "database": "isolated temporary per run",
            "probe": "actual current-platform resource probe",
            "microphone": False,
        },
        "limitations": [
            "Synthetic instant utterances stress the writer beyond normal dictation cadence.",
            "Closed utterances never probe during writer drain; missing samples remain unknown.",
            "Active waits permit periodic probes; they do not simulate audio or inference load.",
            "CPU includes this process and writer, excluding external GPU-query process CPU.",
            "No inference, audio, clipboard, physical keyboard, or interactive desktop exercised.",
            "Results do not establish capture integrity or real dictation latency acceptance.",
        ],
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--utterances", type=int, default=60)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--pause", type=float, default=0.005)
    parser.add_argument("--active-seconds", type=float, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = compare(
        utterances=args.utterances,
        repeats=args.repeats,
        pause_s=args.pause,
        active_seconds=args.active_seconds,
    )
    content = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(content, encoding="utf-8")
    else:
        print(content, end="")


if __name__ == "__main__":
    main()
