# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure evidence guards. Mutation checks are recorded in the checkpoint report."""

import json
import threading

import pytest

from stenographer.capture_metrics import CallbackClock, elapsed_ms
from stenographer.cleanup import select_text, source_hash, validate_output
from stenographer.evaluation import Chunk, alignment, completed_chunks, distribution
from stenographer.inference import Failure, Request, Result
from stenographer.transcribe.pipeline import UtteranceRecord, summary_fields


def test_callback_clock_separates_origins_and_detects_gaps_and_resets():
    clock = CallbackClock()
    clock.observe(callback_at=2.005, adc_at=100, frames=800, rate=16000)
    clock.observe(callback_at=2.055, adc_at=100.05, frames=800, rate=16000)
    assert clock.adc_discontinuities == 0
    clock.observe(callback_at=2.125, adc_at=100.12, frames=800, rate=16000)
    clock.observe(callback_at=2.175, adc_at=1, frames=800, rate=16000)
    assert clock.first_callback_at == 2.005
    assert elapsed_ms(2, clock.first_callback_at) == pytest.approx(5)
    assert clock.adc_discontinuities == 2
    assert clock.max_adc_gap_ms == pytest.approx(99170)
    assert elapsed_ms(2, None) is None
    fields = summary_fields(UtteranceRecord(utt=1, press_to_callback_ms=5.432))
    assert fields["press_to_callback_ms"] == 5.4
    assert fields["max_adc_gap_ms"] is None


@pytest.mark.parametrize("unavailable", [0, float("nan"), float("inf")])
def test_unavailable_adc_clock_does_not_invent_continuity(unavailable):
    clock = CallbackClock()
    clock.observe(callback_at=2, adc_at=100, frames=800, rate=16000)
    clock.observe(callback_at=3, adc_at=unavailable, frames=800, rate=16000)
    clock.observe(callback_at=4, adc_at=102, frames=800, rate=16000)
    assert clock.max_adc_gap_ms is None
    assert clock.adc_discontinuities == 0


def test_alignment_counts_omissions_and_additions_without_calling_them_hallucinations():
    scores = alignment("keep the final sentence", "keep final sentence thank you")
    assert scores["errors"] == 3
    assert scores["deletions"] == 1
    assert scores["insertions"] == scores["tail_insertions"] == 2
    assert scores["opening_exact"] == 0
    assert alignment("yes yes", "yes")["deletions"] == 1
    assert alignment("speech", "")["empty"] == 1
    assert alignment("", "invented")["insertions"] == 1
    assert alignment("", "")["opening_exact"] == 0
    assert alignment("do NOT change 12", "Do not change 12.")["errors"] == 0


def test_latency_statistics_and_chunk_planning_do_not_count_missing_work():
    assert distribution([]) == dict(n=0, median=None, p95=None)
    assert distribution(list(range(1, 21))) == dict(n=20, median=10.5, p95=19)
    with pytest.raises(ValueError):
        distribution([float("nan")])
    assert completed_chunks(9, size=10, overlap=2) == ()
    assert completed_chunks(19, size=10, overlap=2) == (Chunk(0, 10), Chunk(8, 18))
    with pytest.raises(ValueError):
        completed_chunks(20, size=10, overlap=10)


def validate(original, document, **kwargs):
    return validate_output(
        original,
        json.dumps(document),
        strategy="edits",
        finish_reason="stop",
        input_complete=True,
        **kwargs,
    )


def test_unicode_edits_anchor_original_offsets_and_preserve_paragraphs():
    original = "Éva, um, keep 12.\n\nDo not change β."
    document = dict(
        source_sha256=source_hash(original),
        edits=[
            dict(start=4, end=8, before=" um,", after=""),
        ],
    )
    result = validate(original, document)
    assert result.value == "Éva, keep 12.\n\nDo not change β."
    assert not select_text(original, result).cleanup_skipped
    assert "Éva" not in repr(result)
    document["source_sha256"] = source_hash(original + "changed")
    assert validate(original, document).failure is Failure.INVALID


@pytest.mark.parametrize(
    "edits",
    [
        [dict(start=True, end=1, before="", after="x")],
        [dict(start=-1, end=1, before="", after="x")],
        [dict(start=0, end=2, before="no", after="")],
        [dict(start=0, end=2, before="um", after=42)],
        [dict(start=0, end=2, before="um", after=""), dict(start=1, end=3, before="m ", after="")],
        [dict(start=0, end=0, before="", after="x"), dict(start=0, end=0, before="", after="y")],
    ],
)
def test_invalid_edits_retain_exact_original_once(edits):
    original = "um keep 12.\n\nDo not change β. "
    result = validate(original, dict(source_sha256=source_hash(original), edits=edits))
    assert result.failure is Failure.INVALID
    selected = select_text(original, result)
    assert selected.text == original
    assert selected.cleanup_skipped


@pytest.mark.parametrize(
    ("response", "finish", "complete", "failure"),
    [
        ("", "stop", True, Failure.INVALID),
        ("partial", "length", True, Failure.INVALID),
        ("complete", "stop", False, Failure.CONTEXT),
        ("<think>private</think>Text", "stop", True, Failure.INVALID),
        ("text\x00", "stop", True, Failure.INVALID),
    ],
)
def test_rewrites_fail_closed(response, finish, complete, failure):
    result = validate_output(
        "Original", response, strategy="rewrite", finish_reason=finish, input_complete=complete
    )
    assert result.failure is failure
    assert select_text("Original", result).text == "Original"


def test_cancellation_outranks_timeout_and_never_delivers_fallback():
    cancel = threading.Event()
    request = Request(1, deadline=10, cancel=cancel)
    assert request.failure_at(9) is None
    assert request.failure_at(10) is Failure.TIMEOUT
    cancel.set()
    assert request.failure_at(11) is Failure.CANCELLED
    assert select_text("Private", Result(failure=Failure.CANCELLED)).text is None
    for kwargs in ({}, dict(value="text", failure=Failure.CRASH)):
        with pytest.raises(ValueError):
            Result(**kwargs)
