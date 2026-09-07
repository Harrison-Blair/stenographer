# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure study scoring and scheduling. No quality verdict from alignment alone."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", text.lower())


def alignment(reference: str, hypothesis: str) -> dict[str, int]:
    """Levenshtein alignment with deterministic match/sub/delete/insert tie order.

    Two rows of numeric costs avoid quadratic Python-object memory on 10-minute
    recordings. A byte per cell retains the alignment for endpoint diagnostics.
    Tail insertions are a review flag, never a hallucination detector.
    """
    ref, hyp = words(reference), words(hypothesis)
    width = len(hyp) + 1
    trace = bytearray((len(ref) + 1) * width)
    trace[1:width] = bytes([3]) * len(hyp)
    prev = list(range(width))
    for i, token in enumerate(ref, 1):
        row = [i]
        trace[i * width] = 2
        for j, other in enumerate(hyp, 1):
            choices = (prev[j - 1] + (token != other), prev[j] + 1, row[j - 1] + 1)
            cost = min(choices)
            operation = choices.index(cost) + 1
            trace[i * width + j] = operation
            row.append(cost)
        prev = row
    i, j = len(ref), len(hyp)
    counts = dict(substitutions=0, deletions=0, insertions=0, tail_insertions=0)
    at_tail = True
    while i or j:
        operation = trace[i * width + j]
        if operation == 3:
            counts["insertions"] += 1
            counts["tail_insertions"] += int(at_tail)
            j -= 1
        elif operation == 2:
            counts["deletions"] += 1
            i -= 1
            at_tail = False
        else:
            counts["substitutions"] += int(ref[i - 1] != hyp[j - 1])
            i, j = i - 1, j - 1
            at_tail = False
    return dict(
        errors=prev[-1],
        reference_words=len(ref),
        opening_exact=int(bool(ref) and hyp[: min(4, len(ref))] == ref[: min(4, len(ref))]),
        empty=int(not hyp),
        **counts,
    )


def distribution(values: list[float]) -> dict[str, float | int | None]:
    """Median and nearest-rank p95. Missing evidence stays missing."""
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("timings must be finite and nonnegative")
    if not values:
        return dict(n=0, median=None, p95=None)
    ordered = sorted(values)
    middle = len(ordered) // 2
    median = (ordered[middle] + ordered[(len(ordered) - 1) // 2]) / 2
    return dict(n=len(values), median=median, p95=ordered[math.ceil(len(values) * 0.95) - 1])


@dataclass(frozen=True)
class Chunk:
    start: int
    end: int


def completed_chunks(available: int, *, size: int, overlap: int) -> tuple[Chunk, ...]:
    """Completed windows only. The caller submits at most one, keeping audio.

    Backpressure must skip submission (and fall back at stop), never block the
    callback. This helper is planning math, not a production streaming engine.
    """
    if available < 0 or not 0 <= overlap < size:
        raise ValueError("invalid chunk geometry")
    return tuple(
        Chunk(start, start + size) for start in range(0, available - size + 1, size - overlap)
    )
