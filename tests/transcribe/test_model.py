# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for model.py helpers. No WhisperModel / network mocking."""

from __future__ import annotations

import math

import pytest

from stenographer.transcribe.model import (
    PathologicalOutputError,
    SegmentInfo,
    WordInfo,
    _assemble,
    _token_budget,
    _validate_output,
    resolve_cpu_threads,
)


def test_resolve_cpu_threads_explicit_passthrough():
    # An explicit config value wins even when the host counted its cores.
    assert resolve_cpu_threads(3, 16) == 3


def test_resolve_cpu_threads_uses_physical_core_count():
    assert resolve_cpu_threads(0, 4) == 4


def test_resolve_cpu_threads_caps_at_eight():
    # CTranslate2 scales badly past eight threads, so a big machine is capped.
    assert resolve_cpu_threads(0, 16) == 8


def test_resolve_cpu_threads_falls_back_when_host_cannot_count():
    # None is the host saying "cannot tell" (no affinity call, unreadable
    # topology, Windows stub) — never a guess derived from logical CPUs.
    assert resolve_cpu_threads(0, None) == 4


@pytest.mark.parametrize("count", [0, -1])
def test_resolve_cpu_threads_falls_back_on_nonsense_count(count):
    assert resolve_cpu_threads(0, count) == 4


def test_token_budget_short_audio_is_small():
    assert _token_budget(128, 0.1) == 17


def test_token_budget_rises_with_duration():
    assert _token_budget(128, 0.1) < _token_budget(128, 5.0)


def test_token_budget_never_exceeds_configured_max():
    assert _token_budget(128, 1000.0) == 128


def test_token_budget_matches_formula():
    assert _token_budget(128, 2.0) == min(128, 16 + math.ceil(8 * 2.0))


def _valid_kwargs():
    return {
        "segment_timestamps": [(0.0, 1.0)],
        "word_timestamps": [(0.0, 0.5), (0.5, 1.0)],
        "word_count": 2,
        "audio_seconds": 2.0,
        "vad_seconds": 1.5,
    }


def test_validate_output_accepts_plausible_utterance():
    _validate_output(**_valid_kwargs())  # does not raise


def test_validate_output_rejects_end_before_start():
    kwargs = _valid_kwargs()
    kwargs["segment_timestamps"] = [(1.0, 0.5)]
    with pytest.raises(PathologicalOutputError):
        _validate_output(**kwargs)


def test_validate_output_rejects_timestamp_past_audio():
    kwargs = _valid_kwargs()
    kwargs["audio_seconds"] = 1.0
    kwargs["word_timestamps"] = [(0.0, 5.0)]
    with pytest.raises(PathologicalOutputError):
        _validate_output(**kwargs)


def test_validate_output_rejects_nonfinite_vad():
    kwargs = _valid_kwargs()
    kwargs["vad_seconds"] = math.inf
    with pytest.raises(PathologicalOutputError):
        _validate_output(**kwargs)


def test_validate_output_rejects_negative_vad():
    kwargs = _valid_kwargs()
    kwargs["vad_seconds"] = -0.1
    with pytest.raises(PathologicalOutputError):
        _validate_output(**kwargs)


def test_validate_output_rejects_word_density_runaway():
    kwargs = _valid_kwargs()
    kwargs["vad_seconds"] = 1.0  # limit = max(12, ceil(8*1)) = 12
    kwargs["word_count"] = 13
    with pytest.raises(PathologicalOutputError):
        _validate_output(**kwargs)


def test_validate_output_message_has_no_transcript_text():
    # The word "hello" is never passed in; the message must be counts-only.
    kwargs = _valid_kwargs()
    kwargs["vad_seconds"] = 1.0
    kwargs["word_count"] = 13
    with pytest.raises(PathologicalOutputError) as exc:
        _validate_output(**kwargs)
    message = str(exc.value)
    assert "13" in message and "12" in message
    assert not any(c.isalpha() for c in message.split("(", 1)[1])


def _segment(start, end, text, no_speech_prob, words=None):
    return SegmentInfo(
        start=start,
        end=end,
        text=text,
        no_speech_prob=no_speech_prob,
        words=words or [],
    )


def test_assemble_drops_silence_segments_and_concatenates():
    w1 = WordInfo(0.0, 0.5, "hi", 0.9)
    w2 = WordInfo(1.0, 1.5, "there", 0.9)
    segments = [
        _segment(0.0, 0.5, "hi ", 0.1, [w1]),
        _segment(0.6, 0.9, " Thank you.", 0.8, [WordInfo(0.6, 0.9, "Thank", 0.5)]),
        _segment(1.0, 1.5, "there", 0.2, [w2]),
    ]
    result = _assemble(segments, silence_threshold=0.6, audio_seconds=2.0, vad_seconds=1.5)
    assert result.text == "hi there"
    assert result.duration_seconds == 2.0
    # The 0.8 no_speech_prob segment (>= 0.6) is dropped; survivors keep words.
    assert len(result.segments) == 2
    assert result.segments[0].words == [w1]
    assert result.segments[1].words == [w2]


def test_assemble_boundary_segment_at_threshold_is_dropped():
    segments = [_segment(0.0, 1.0, "edge", 0.6, [WordInfo(0.0, 1.0, "edge", 0.9)])]
    result = _assemble(segments, silence_threshold=0.6, audio_seconds=1.5, vad_seconds=1.0)
    assert result.text == ""
    assert result.segments == []


def test_assemble_validates_survivor_word_density():
    words = [WordInfo(0.0, 0.01, "x", 0.9) for _ in range(13)]
    segments = [_segment(0.0, 1.0, "x" * 13, 0.1, words)]
    with pytest.raises(PathologicalOutputError):
        _assemble(segments, silence_threshold=0.6, audio_seconds=1.5, vad_seconds=1.0)
