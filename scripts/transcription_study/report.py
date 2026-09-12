# SPDX-License-Identifier: GPL-3.0-or-later
"""Aggregate explicit benchmark result files without reading speech or transcripts.

Run with ``.venv/bin/python scripts/transcription_study/report.py RESULTS...``.
Outputs numeric JSON; each profile/clip may occur only once in the input set.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path


def percentile(values: list[float], fraction: float) -> float | None:
    """Linearly interpolated percentile; missing observations remain missing."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def stage_totals(rows: list[dict], stage: str) -> dict:
    """Aggregate word errors with their own coverage, without averaging clip WERs."""
    scores = [row.get("stages", {}).get(stage) for row in rows]
    scores = [score for score in scores if score is not None]
    totals = {key: sum(score[key] for score in scores) for key in ("S", "D", "I", "N")}
    errors = sum(totals[key] for key in ("S", "D", "I"))
    speech_errors = sum(score["S"] + score["D"] + score["I"] for score in scores if score["N"] > 0)
    silence = [score for score in scores if score["N"] == 0]
    speech = [score for score in scores if score["N"] > 0]
    return {
        **totals,
        "errors_including_nonspeech": errors,
        "speech_errors": speech_errors,
        "wer": speech_errors / totals["N"] if totals["N"] else None,
        "scored_clips": len(scores),
        "speech_clips": len(speech),
        "exact_speech_clips": sum(bool(score["exact"]) for score in speech),
        "opening_correct": sum(bool(score["opening_correct"]) for score in speech),
        "closing_correct": sum(bool(score["closing_correct"]) for score in speech),
        "nonspeech_clips": len(silence),
        "nonspeech_false_positives": sum(score["I"] > 0 for score in silence),
        "nonspeech_inserted_words": sum(score["I"] for score in silence),
    }


def summarize(rows: list[dict]) -> dict:
    """Describe quality and observed processing cost; never infer missing metrics."""
    latencies = [float(row["wall_seconds"]) for row in rows if "wall_seconds" in row]
    decode_times = [float(row["decode_seconds"]) for row in rows if "decode_seconds" in row]
    warm_times = [
        float(row["decode_seconds"])
        for row in rows
        if row.get("first_decode_in_worker") is False
        and "decode_seconds" in row
        and row.get("gate", {"passed": True})["passed"]
    ]
    stage_names = sorted({name for row in rows for name in row.get("stages", {})})
    durations = sum(row.get("audio_seconds", 0) for row in rows)
    refinements = [row["refinement"] for row in rows if row.get("refinement") is not None]
    return {
        "clips": len(rows),
        "groups": len({row["group"] for row in rows}),
        "stages": {name: stage_totals(rows, name) for name in stage_names},
        "statuses": {
            status: sum(row["status"] == status for row in rows)
            for status in sorted({row["status"] for row in rows})
        },
        "wall_seconds_median": statistics.median(latencies) if latencies else None,
        "wall_seconds_p95": percentile(latencies, 0.95),
        "decode_seconds_median": percentile(decode_times, 0.5),
        "decode_seconds_p95": percentile(decode_times, 0.95),
        "warm_decode_clips": len(warm_times),
        "warm_decode_seconds_median": percentile(warm_times, 0.5),
        "warm_decode_seconds_p95": percentile(warm_times, 0.95),
        "processing_seconds_per_audio_second": sum(latencies) / durations if durations else None,
        "rss_peak_bytes": max(
            (row["rss_peak_bytes"] for row in rows if row.get("rss_peak_bytes") is not None),
            default=None,
        ),
        "refinement": {
            "outcomes": {
                outcome: sum(r["outcome"] == outcome for r in refinements)
                for outcome in sorted({r["outcome"] for r in refinements})
            },
            "duration_ms_median": percentile([r["duration_ms"] for r in refinements], 0.5),
            "duration_ms_p95": percentile([r["duration_ms"] for r in refinements], 0.95),
            "protected_lexical_counts": {
                category: {
                    key: sum(r["protected_metrics"][category][key] for r in refinements)
                    for key in (
                        "reference",
                        "input_matching",
                        "output_matching",
                        "lost_correct",
                        "gained_correct",
                        "added_nonreference",
                    )
                }
                for category in ("numbers", "negations", "names")
            }
            if refinements
            else {},
            "cleanup_accuracy_evaluated": False,
        },
        "by_corpus": {
            corpus: {
                name: stage_totals([r for r in rows if r["corpus"] == corpus], name)
                for name in stage_names
            }
            for corpus in sorted({row["corpus"] for row in rows})
        },
    }


def paired_comparison(
    baseline: list[dict], candidate: list[dict], *, stage: str = "formatted", repeats: int = 2000
) -> dict:
    """Cluster-bootstrap matched utterances; variants of a source are not independent."""
    base = {(r["split"], r["clip_id"]): r for r in baseline}
    pairs = [
        (base[(r["split"], r["clip_id"])], r)
        for r in candidate
        if (r["split"], r["clip_id"]) in base
    ]
    clusters: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    improved = worsened = unchanged = 0
    for first, second in pairs:
        a = first.get("stages", {}).get(stage)
        b = second.get("stages", {}).get(stage)
        if a is None or b is None or not a["N"]:
            continue
        if a["N"] != b["N"] or first["group"] != second["group"]:
            raise ValueError("matched clips have inconsistent references or groups")
        errors_a = a["S"] + a["D"] + a["I"]
        errors_b = b["S"] + b["D"] + b["I"]
        clusters[first["group"]].append((errors_a, errors_b, a["N"]))
        improved += errors_b < errors_a
        worsened += errors_b > errors_a
        unchanged += errors_b == errors_a
    totals = [tuple(sum(v[i] for v in group) for i in range(3)) for group in clusters.values()]
    words = sum(value[2] for value in totals)
    delta = sum(b - a for a, b, _ in totals) / words if words else None
    bounds = None
    if len(totals) >= 2 and repeats > 0:
        rng = random.Random(20260912)
        estimates = []
        for _ in range(repeats):
            sample = rng.choices(totals, k=len(totals))
            estimates.append(sum(b - a for a, b, _ in sample) / sum(n for _, _, n in sample))
        bounds = [percentile(estimates, 0.025), percentile(estimates, 0.975)]
    return {
        "stage": stage,
        "matched_speech_clips": improved + worsened + unchanged,
        "matched_reference_words": words,
        "groups": len(totals),
        "improved_clips": improved,
        "worsened_clips": worsened,
        "unchanged_clips": unchanged,
        "wer_delta_candidate_minus_baseline": delta,
        "cluster_bootstrap_95_interval": bounds,
        "bootstrap_repeats": repeats if bounds is not None else 0,
    }


def aggregate(rows: list[dict]) -> dict:
    """Keep development and held-out reports separate and reject duplicate observations."""
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    seen = set()
    for row in rows:
        if row.get("refinement") is not None:
            row = {**row, "stages": {**row["stages"], "refined": row["refinement"]}}
        key = (row["split"], row["profile"], row["clip_id"])
        if key in seen:
            raise ValueError("duplicate split/profile/clip; select one explicit result set")
        seen.add(key)
        grouped[row["split"], row["profile"]].append(row)
    result = {}
    for split in sorted({key[0] for key in grouped}):
        for (part, _), values in grouped.items():
            if part == split and len({r["fingerprint"] for r in values}) != 1:
                raise ValueError("mixed fingerprints for one split/profile; select a single run")
        baseline = grouped.get((split, "baseline"), [])
        result[split] = {
            profile: {
                **summarize(values),
                "paired_with_baseline": paired_comparison(baseline, values),
                "fingerprints": sorted({r["fingerprint"] for r in values}),
            }
            for (part, profile), values in sorted(grouped.items())
            if part == split
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path, nargs="+")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows = []
    reference_identity = None
    for path in args.results:
        contents = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        metadata = json.loads(Path(str(path) + ".meta.json").read_text())
        for row in contents:
            record = metadata[row["fingerprint"]]
            identity = {
                key: record[key]
                for key in (
                    "manifest_sha256",
                    "config",
                    "versions",
                    "sources",
                    "backend",
                    "host",
                    "model",
                    "normalization",
                    "python",
                )
            }
            if reference_identity is not None and identity != reference_identity:
                raise ValueError("incompatible run metadata; report these experiments separately")
            reference_identity = identity
        rows.extend(contents)
    payload = json.dumps(aggregate(rows), indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(payload)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
