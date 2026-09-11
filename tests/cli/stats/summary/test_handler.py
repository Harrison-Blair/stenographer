# SPDX-License-Identifier: GPL-3.0-or-later
"""The summary report rendered from a real store's own arithmetic."""

from __future__ import annotations

from stenographer.cli.stats.summary.handler import _duration, run
from stenographer.lib.analytics.filters import Filters

from ..conftest import checkpoint


def test_duration_renders_hours_minutes_and_seconds_zero_padded():
    assert _duration(0) == "00:00:00"
    assert _duration(59.9) == "00:00:59"
    assert _duration(3661) == "01:01:01"
    assert _duration(360000) == "100:00:00"


def test_summary_totals_thousands_durations_and_headline_counts(seed, capsys):
    store = seed(
        checkpoint(
            "utt-1",
            started_at="2026-03-05T12:00:00.000000+00:00",
            recognized_words=1200,
            copied_words=1100,
            chord_words=1000,
            asr_audio_s=3661.0,
        ),
        checkpoint(
            "utt-2",
            started_at="2026-03-05T13:00:00.000000+00:00",
            recognized_words=300,
            copied_words=200,
            chord_words=100,
            asr_audio_s=1.0,
        ),
    )

    assert run(None, store, Filters()) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "Recognized words: 1,500"
    assert lines[1] == "Completed ASR audio: 01:01:02"
    assert lines[2] == "Utterances: 2 · Active days: 1"
    assert lines[3] == "Clipboard-confirmed words: 1,300"
    assert lines[4] == "Paste-chord words: 1,100"
    assert lines[5] == "Incomplete utterances: 0"


def test_summary_counts_an_unfinished_utterance_as_incomplete(seed, capsys):
    store = seed(checkpoint("utt-1", phase="accepted_start", outcome=None, recognized_words=4))

    assert run(None, store, Filters()) == 0
    assert "Incomplete utterances: 1" in capsys.readouterr().out


def test_summary_reports_only_measured_millisecond_metrics(seed, capsys):
    store = seed(
        checkpoint("utt-1", round_trip_ms=100.0, recognized_words=1),
        checkpoint("utt-2", round_trip_ms=200.0, recognized_words=1),
    )

    assert run(None, store, Filters()) == 0

    out = capsys.readouterr().out
    assert "round_trip_ms: average 150.0, p95 200.0, p99 200.0 ms (n=2, missing=0)" in out
    # A metric nothing measured has no distribution worth printing.
    assert "decode_ms:" not in out


def test_summary_honours_its_filters_and_closes_with_the_collection_health(seed, capsys):
    store = seed(
        checkpoint("hotkey-1", source="hotkey", recognized_words=5),
        checkpoint("file-1", source="file", recognized_words=50),
    )

    assert run(None, store, Filters(source="file")) == 0

    out = capsys.readouterr().out
    assert "Recognized words: 50" in out
    assert out.splitlines()[-1] == "Collection: available; dropped checkpoints: 0"


def test_summary_reports_a_degraded_collection_and_its_dropped_count(seed, capsys):
    store = seed(checkpoint("utt-1", recognized_words=1))
    store.register_run("run", {})
    store.update_health("run", {"degraded": True, "dropped_checkpoints": 7})

    assert run(None, store, Filters()) == 0
    assert (
        capsys.readouterr().out.splitlines()[-1] == "Collection: degraded; dropped checkpoints: 7"
    )
