# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the word-level decode path used by incremental decoding."""

from __future__ import annotations

import numpy as np

from stenographer.asr.model import Model


class _FakeWord:
    def __init__(self, word: str, start: float, end: float) -> None:
        self.word = word
        self.start = start
        self.end = end
        self.probability = 1.0


class _FakeSegment:
    def __init__(self, no_speech_prob: float, *words: str) -> None:
        self.no_speech_prob = no_speech_prob
        self.words = [_FakeWord(w, i * 0.5, (i + 1) * 0.5) for i, w in enumerate(words)]


class _FakeImpl:
    def __init__(self, segments: list[_FakeSegment]) -> None:
        self.segments = segments

    def transcribe(self, samples, **kwargs):
        return iter(self.segments), None


def _model(segments: list[_FakeSegment], *, silence_threshold: float = 0.6) -> Model:
    """A Model with a stub backend, bypassing the real WhisperModel load."""
    m = object.__new__(Model)
    m._impl = _FakeImpl(segments)
    m._language = "en"
    m._beam_size = 1
    m._hotwords = None
    m._initial_prompt = None
    m._silence_threshold = silence_threshold
    return m


def _samples() -> np.ndarray:
    return np.zeros(16000, dtype=np.float32)


def test_probable_silence_segments_are_dropped_from_word_decode() -> None:
    # Whisper hallucinates over silence; word decoding must apply the same
    # no_speech_prob gate the batch path does, or "Thank you." reaches the
    # cursor after a hotkey press with no speech.
    model = _model([_FakeSegment(0.99, " Thank", " you.")])
    assert model.transcribe_words(_samples()) == []


def test_speech_segments_survive_the_silence_gate() -> None:
    model = _model([_FakeSegment(0.02, " hello", " world")])
    assert [w.word for w in model.transcribe_words(_samples())] == [" hello", " world"]


def test_only_the_silent_segment_is_dropped() -> None:
    model = _model(
        [
            _FakeSegment(0.02, " hello"),
            _FakeSegment(0.95, " Thanks", " for", " watching."),
            _FakeSegment(0.1, " world"),
        ]
    )
    assert [w.word for w in model.transcribe_words(_samples())] == [" hello", " world"]


def test_silence_threshold_boundary_is_inclusive() -> None:
    model = _model([_FakeSegment(0.6, " maybe")], silence_threshold=0.6)
    assert model.transcribe_words(_samples()) == []
