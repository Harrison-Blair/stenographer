# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the word-level decode path used by incremental decoding."""

from __future__ import annotations

import numpy as np
import pytest

from stenographer.asr.model import (
    Model,
    PathologicalOutputError,
    _token_budget,
    resolve_cpu_threads,
)
from stenographer.config import Config


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
    m._vad_filter = True
    m._max_new_tokens = 128
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


def test_invalid_word_timestamp_is_rejected_without_logging_text(caplog) -> None:
    segment = _FakeSegment(0.1, " private-dictation")
    segment.words[0].start = float("nan")
    model = _model([segment])

    with pytest.raises(PathologicalOutputError, match="timestamp"):
        model.transcribe_words(_samples())
    assert "private-dictation" not in caplog.text


def test_implausible_word_density_is_rejected() -> None:
    segment = _FakeSegment(0.1, *(f" word{i}" for i in range(13)))
    for index, word in enumerate(segment.words):
        word.start = index / 20
        word.end = (index + 1) / 20
    model = _model([segment])

    with pytest.raises(PathologicalOutputError, match="density"):
        model.transcribe_words(_samples())


def test_interim_token_budget_is_smaller_than_final_budget() -> None:
    assert _token_budget(128, 2.0, interim=True) == 22
    assert _token_budget(128, 2.0) == 32
    assert _token_budget(20, 30.0, interim=True) == 20


def test_cpu_thread_resolution_counts_affinity_visible_physical_cores(tmp_path) -> None:
    for cpu, package, core in [(0, 0, 0), (1, 0, 0), (2, 0, 1), (3, 1, 0)]:
        topology = tmp_path / f"cpu{cpu}" / "topology"
        topology.mkdir(parents=True)
        (topology / "physical_package_id").write_text(str(package))
        (topology / "core_id").write_text(str(core))

    assert resolve_cpu_threads(0, affinity={0, 1, 2, 3}, topology_root=tmp_path) == 3


def test_cpu_thread_resolution_caps_auto_and_falls_back(tmp_path) -> None:
    for cpu in range(10):
        topology = tmp_path / f"cpu{cpu}" / "topology"
        topology.mkdir(parents=True)
        (topology / "physical_package_id").write_text("0")
        (topology / "core_id").write_text(str(cpu))

    assert resolve_cpu_threads(0, affinity=set(range(10)), topology_root=tmp_path) == 8
    assert resolve_cpu_threads(0, affinity={99}, topology_root=tmp_path) == 4
    assert resolve_cpu_threads(12, affinity=set(), topology_root=tmp_path) == 12


def test_model_passes_resolved_cpu_threads_to_backend(monkeypatch) -> None:
    received: dict[str, object] = {}

    class FakeWhisperModel:
        def __init__(self, _model: str, **kwargs) -> None:
            received.update(kwargs)

    monkeypatch.setattr("stenographer.asr.model.WhisperModel", FakeWhisperModel)
    monkeypatch.setattr("stenographer.asr.model.resolve_cpu_threads", lambda _value: 6)

    model = Model(Config.defaults().asr)

    assert received["cpu_threads"] == 6
    model.close()
