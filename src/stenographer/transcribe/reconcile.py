# SPDX-License-Identifier: GPL-3.0-or-later
"""Conservative, experimental timed overlap reconciliation. Not daemon-wired."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import pairwise

from stenographer.evaluation import words
from stenographer.inference import Failure, Result
from stenographer.transcribe.model import TranscriptionResult, WordInfo


@dataclass(frozen=True)
class Window:
    start: float
    end: float
    result: TranscriptionResult = field(repr=False)


def reconcile(windows: list[Window], duration: float) -> Result[str]:
    """Require complete audio coverage and matching timed words at every seam.

    Strings alone are insufficient: intentional repetition must survive. Every
    word whose midpoint lies inside the overlap must agree in order and time
    (150 ms tolerance), with at least two matching words. Join at a matched
    word's index, never two independently rounded timestamps. A silent seam,
    missing timestamps, differing counts or uncertain coverage requests whole
    utterance decoding. Passing this check still requires corpus/human evaluation.
    """
    if (
        not math.isfinite(duration)
        or duration <= 0
        or not windows
        or windows[0].start != 0
        or windows[-1].end != duration
    ):
        return Result(failure=Failure.UNCERTAIN)
    merged: list[WordInfo] = []
    previous_end = 0.0
    for window in windows:
        if (
            not math.isfinite(window.start)
            or not math.isfinite(window.end)
            or window.start < 0
            or window.end <= max(window.start, previous_end)
        ):
            return Result(failure=Failure.UNCERTAIN)
        current = [
            WordInfo(w.start + window.start, w.end + window.start, w.word, w.probability)
            for segment in window.result.segments
            for w in segment.words
        ]
        if not current or any(
            not math.isfinite(w.start)
            or not math.isfinite(w.end)
            or w.start < window.start
            or w.end > window.end
            or w.end < w.start
            for w in current
        ):
            return Result(failure=Failure.UNCERTAIN)
        if words("".join(w.word for w in current)) != words(window.result.text):
            return Result(failure=Failure.UNCERTAIN)
        if any(a.start > b.start for a, b in pairwise(current)):
            return Result(failure=Failure.UNCERTAIN)
        if merged:
            if window.start >= previous_end:
                return Result(failure=Failure.UNCERTAIN)
            left = [
                i
                for i, w in enumerate(merged)
                if window.start <= (w.start + w.end) / 2 < previous_end
            ]
            right = [
                i
                for i, w in enumerate(current)
                if window.start <= (w.start + w.end) / 2 < previous_end
            ]
            if len(left) < 2 or len(left) != len(right):
                return Result(failure=Failure.UNCERTAIN)
            for a, b in zip(left, right, strict=True):
                old, new = merged[a], current[b]
                if (
                    words(old.word) != words(new.word)
                    or abs(old.start - new.start) > 0.15
                    or abs(old.end - new.end) > 0.15
                ):
                    return Result(failure=Failure.UNCERTAIN)
            anchor = len(left) // 2
            merged = merged[: left[anchor]] + current[right[anchor] :]
        else:
            merged = current
        previous_end = window.end
    return Result(value="".join(w.word for w in merged).strip())
