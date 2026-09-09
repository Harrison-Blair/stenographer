# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure timed-seam checks; passing is not recognition fidelity acceptance."""

from dataclasses import replace

from stenographer.inference import Failure
from stenographer.transcribe.model import SegmentInfo, TranscriptionResult, WordInfo
from stenographer.transcribe.reconcile import Window, reconcile


def window(start, end, entries):
    tokens = [WordInfo(t - start, t - start + 0.2, " " + word, 0.9) for t, word in entries]
    text = "".join(w.word for w in tokens).strip()
    return Window(
        start,
        end,
        TranscriptionResult(text, end - start, [SegmentInfo(0, end - start, text, 0.1, tokens)]),
    )


def test_reconciliation_preserves_intentional_repetition_and_joins_by_matched_index():
    first = window(0, 5, [(0, "very"), (2, "very"), (3, "important"), (4, "today")])
    second = window(2, 7, [(2.02, "very"), (3.02, "important"), (4.02, "today"), (6, "indeed")])
    result = reconcile([first, second], 7)
    assert result.value == "very very important today indeed"
    assert "important" not in repr(first)


def test_uncertain_seams_missing_coverage_and_lost_words_request_whole_audio():
    first = window(0, 5, [(0, "very"), (2, "very"), (3, "important"), (4, "today")])
    variants = [
        window(2, 7, [(3, "important"), (4, "today"), (6, "indeed")]),
        window(2, 7, [(2.3, "very"), (3, "important"), (4, "today"), (6, "indeed")]),
        window(5, 7, [(6, "indeed")]),
        window(2, 7, [(2, "maybe"), (3, "important"), (4, "today"), (6, "indeed")]),
        window(2, 7, [(2, "very"), (3, "important"), (float("nan"), "today")]),
    ]
    for second in variants:
        assert reconcile([first, second], 7).failure is Failure.UNCERTAIN
    assert reconcile([first], 6).failure is Failure.UNCERTAIN
    assert reconcile([replace(first, start=1)], 5).failure is Failure.UNCERTAIN
    assert reconcile([], 0).failure is Failure.UNCERTAIN
