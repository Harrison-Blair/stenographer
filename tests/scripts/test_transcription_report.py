# SPDX-License-Identifier: GPL-3.0-or-later
"""Statistical accounting for the public-audio experiment report."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).parents[2] / "scripts/transcription_study/report.py"
_SPEC = importlib.util.spec_from_file_location("transcription_report", _PATH)
assert _SPEC and _SPEC.loader
report = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(report)


def row(clip, *, n=10, errors=0, group="speaker", profile="baseline", split="dev"):
    return {
        "clip_id": clip,
        "split": split,
        "profile": profile,
        "fingerprint": "test",
        "group": group,
        "corpus": "example",
        "status": "ok",
        "wall_seconds": 1.0,
        "audio_seconds": 2.0,
        "rss_peak_bytes": 1024,
        "stages": {
            "formatted": {
                "S": 0,
                "D": 0,
                "I": errors,
                "N": n,
                "exact": errors == 0,
                "opening_correct": errors == 0,
                "closing_correct": errors == 0,
            }
        },
    }


def test_word_errors_are_weighted_by_reference_words_and_silence_separate():
    rows = [row("short", n=2, errors=1), row("long", n=8), row("silence", n=0, errors=4)]
    value = report.stage_totals(rows, "formatted")
    assert value["wer"] == 0.1
    assert value["nonspeech_false_positives"] == 1
    assert value["nonspeech_inserted_words"] == 4
    assert value["errors_including_nonspeech"] == 5


def test_bootstrap_uses_speaker_groups_and_only_matching_clips():
    baseline = [row("one", errors=2), row("two", errors=2), row("third", group="other")]
    candidate = [row("one"), row("two"), row("missing", errors=90)]
    result = report.paired_comparison(baseline, candidate)
    assert result["groups"] == 1
    assert result["matched_speech_clips"] == 2
    assert result["wer_delta_candidate_minus_baseline"] == -0.2
    assert result["cluster_bootstrap_95_interval"] is None


def test_two_groups_permit_reproducible_paired_interval():
    a = [row("one", errors=2), row("two", errors=2, group="other")]
    b = [row("one"), row("two", group="other")]
    result = report.paired_comparison(a, b)
    assert result["cluster_bootstrap_95_interval"] == pytest.approx([-0.2, -0.2])


def test_mismatched_reference_counts_are_rejected():
    with pytest.raises(ValueError, match="inconsistent references"):
        report.paired_comparison([row("one")], [row("one", n=11)])


def test_duplicate_observations_are_rejected_and_splits_stay_separate():
    with pytest.raises(ValueError, match="duplicate"):
        report.aggregate([row("one"), row("one")])
    result = report.aggregate([row("one"), row("one", split="heldout")])
    assert set(result) == {"dev", "heldout"}


def test_missing_stage_does_not_become_a_successful_empty_transcript():
    missing = row("one")
    missing["stages"]["formatted"] = None
    value = report.stage_totals([missing], "formatted")
    assert value["wer"] is None
    assert value["scored_clips"] == 0


def test_mixed_fingerprints_cannot_be_pooled_even_on_different_clips():
    changed = row("two")
    changed["fingerprint"] = "changed-model"
    with pytest.raises(ValueError, match="mixed fingerprints"):
        report.aggregate([row("one"), changed])


def test_failed_refinement_is_counted_as_failure_even_if_delivered_text_scores_well():
    data = row("one")
    data["refinement"] = {
        **data["stages"]["formatted"],
        "outcome": "failed",
        "duration_ms": 30,
        "protected_metrics": {
            category: dict.fromkeys(
                (
                    "reference",
                    "input_matching",
                    "output_matching",
                    "lost_correct",
                    "gained_correct",
                    "added_nonreference",
                ),
                0,
            )
            for category in ("numbers", "negations", "names")
        },
    }
    value = report.aggregate([data])["dev"]["baseline"]
    assert value["stages"]["refined"]["wer"] == 0
    assert value["refinement"]["outcomes"] == {"failed": 1}
    assert value["refinement"]["cleanup_accuracy_evaluated"] is False


def test_missing_memory_observations_remain_unknown():
    missing = row("one")
    missing["rss_peak_bytes"] = None
    assert report.summarize([missing])["rss_peak_bytes"] is None
    assert report.summarize([missing, row("two")])["rss_peak_bytes"] == 1024


def test_first_decode_is_excluded_from_warm_timing():
    first, warm = row("one"), row("two")
    first.update(first_decode_in_worker=True, decode_seconds=20)
    warm.update(first_decode_in_worker=False, decode_seconds=2)
    assert report.summarize([first, warm])["warm_decode_seconds_median"] == 2
