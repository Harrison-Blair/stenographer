# SPDX-License-Identifier: GPL-3.0-or-later
"""Phrase cutting over the sherpa-onnx VAD interface."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from stenographer.lib.live.models import LIVE_MODELS
from stenographer.lib.live.phrase import Phrase
from stenographer.lib.live.phrase_segmenter import PhraseSegmenter
from stenographer.lib.platform import current_platform


class FakeSegment:
    def __init__(self, start: int, samples: np.ndarray) -> None:
        self.start = start
        self.samples = samples


class FakeVad:
    def __init__(self, *, active: list[FakeSegment], flushed: list[FakeSegment]) -> None:
        self._segments = list(active)
        self._flushed = list(flushed)
        self.accepted: list[np.ndarray] = []
        self.did_flush = False
        self.speech = False

    def is_speech_detected(self) -> bool:
        return self.speech

    def empty(self) -> bool:
        return not self._segments

    @property
    def front(self) -> FakeSegment:
        return self._segments[0]

    def accept_waveform(self, samples: np.ndarray) -> None:
        self.accepted.append(samples.copy())

    def pop(self) -> None:
        self._segments.pop(0)

    def flush(self) -> None:
        self.did_flush = True
        self._segments.extend(self._flushed)
        self._flushed.clear()


class FakeVadConfig:
    def __init__(self) -> None:
        self.silero_vad = SimpleNamespace()

    def validate(self) -> bool:
        return True


class FakeSherpa:
    def __init__(self, vad: FakeVad) -> None:
        self.vad = vad
        self.config: FakeVadConfig | None = None

    def VadModelConfig(self) -> FakeVadConfig:  # noqa: N802
        self.config = FakeVadConfig()
        return self.config

    def VoiceActivityDetector(self, config, *, buffer_size_in_seconds):  # noqa: N802
        assert buffer_size_in_seconds == 120
        return self.vad


def test_phrase_segmenter_uses_d6_vad_values_cuts_long_phrases_and_flushes(monkeypatch):
    vad = FakeVad(
        active=[FakeSegment(1600, np.ones(25600, dtype=np.float32))],
        flushed=[FakeSegment(32000, np.ones(4000, dtype=np.float32))],
    )
    sherpa = FakeSherpa(vad)
    monkeypatch.setitem(sys.modules, "sherpa_onnx", sherpa)
    segmenter = PhraseSegmenter("mic", Path("silero_vad.onnx"), max_phrase_seconds=1)

    active_phrases = segmenter.accept(np.zeros(40000, dtype=np.float32))
    final_phrases = segmenter.flush()

    assert sherpa.config is not None
    assert sherpa.config.silero_vad.threshold == 0.5
    assert sherpa.config.silero_vad.min_speech_duration == 0.25
    assert sherpa.config.silero_vad.min_silence_duration == 0.6
    assert sherpa.config.silero_vad.max_speech_duration == 1
    assert sherpa.config.sample_rate == 16000
    assert sherpa.config.num_threads == 1
    assert sherpa.config.provider == "cpu"
    assert max(map(len, vad.accepted)) <= 512
    assert sum(map(len, vad.accepted)) == 40000
    assert vad.did_flush is True
    assert len(active_phrases) == 2
    for phrase, (start, end) in zip(active_phrases, [(0.1, 1.1), (1.1, 1.7)], strict=True):
        assert phrase.start == pytest.approx(start)
        assert phrase.end == pytest.approx(end)
    assert len(final_phrases) == 1
    assert final_phrases[0].start == pytest.approx(2.0)
    assert final_phrases[0].end == pytest.approx(2.25)
    assert [phrase.samples.size for phrase in active_phrases] == [16000, 9600]
    assert final_phrases[0].samples.size == 4000
    phrases = (*active_phrases, *final_phrases)
    assert all(isinstance(phrase, Phrase) and phrase.source == "mic" for phrase in phrases)
    assert all(phrase.samples.dtype == np.float32 for phrase in (*active_phrases, *final_phrases))
    assert segmenter.flush() == []


def test_phrase_segmenter_reports_the_detector_speech_state(monkeypatch):
    vad = FakeVad(active=[], flushed=[])
    monkeypatch.setitem(sys.modules, "sherpa_onnx", FakeSherpa(vad))
    segmenter = PhraseSegmenter("mic", Path("silero_vad.onnx"))

    assert segmenter.speech_detected is False
    vad.speech = True
    assert segmenter.speech_detected is True


@pytest.mark.integration
def test_phrase_segmenter_with_real_vad_finds_task_one_turns_when_assets_are_present():
    data_dir = current_platform().data_dir(os.environ, Path.home())
    model_path = data_dir / "models" / "live" / LIVE_MODELS[0].filename
    audio_path = (
        Path(__file__).resolve().parents[3] / "tmp" / "live_audio" / "1-two-speakers-en.wav"
    )
    if not model_path.is_file():
        pytest.skip(f"Silero VAD model is absent: {model_path}")
    if not audio_path.is_file():
        pytest.skip(f"Task 1 public VAD sample is absent: {audio_path}")

    audio, rate = sf.read(audio_path, dtype="float32", always_2d=True)
    assert rate == 16000
    segmenter = PhraseSegmenter("system", model_path)
    phrases: list[Phrase] = []
    mono = np.ascontiguousarray(audio[:, 0])
    for offset in range(0, len(mono), 1024):
        phrases.extend(segmenter.accept(mono[offset : offset + 1024]))
    phrases.extend(segmenter.flush())

    expected = [(1.638, 3.368), (4.422, 6.536), (9.382, 11.496), (12.198, 14.696)]
    assert len(phrases) == len(expected)
    for phrase, (start, end) in zip(phrases, expected, strict=True):
        assert phrase.start == pytest.approx(start, abs=0.3)
        assert phrase.end == pytest.approx(end, abs=0.3)
        assert phrase.source == "system"
