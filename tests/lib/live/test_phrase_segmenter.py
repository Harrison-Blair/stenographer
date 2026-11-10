# SPDX-License-Identifier: GPL-3.0-or-later
"""Phrase cutting over the sherpa-onnx VAD interface."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from stenographer.lib.live.models import vad_model_path
from stenographer.lib.live.phrase_segmenter import Phrase, PhraseSegmenter, detector_gain


class FakeSegment:
    def __init__(self, start: int, samples: np.ndarray) -> None:
        self.start = start
        self.samples = samples


class FakeVad:
    """sherpa-onnx's detector: a segment holds the samples that it received.

    *active* and *flushed* are ``(start, length)`` frame ranges, released once
    the detector has received them (the flushed ones only at ``flush``).
    """

    def __init__(self, *, active: list[tuple[int, int]], flushed: list[tuple[int, int]]) -> None:
        self._ranges = list(active)
        self._flushed = list(flushed)
        self._segments: list[FakeSegment] = []
        self.accepted: list[np.ndarray] = []
        self.did_flush = False
        self.speech = False

    def _release(self) -> None:
        heard = np.concatenate(self.accepted) if self.accepted else np.empty(0, np.float32)
        while self._ranges and sum(self._ranges[0]) <= heard.size:
            start, length = self._ranges.pop(0)
            self._segments.append(FakeSegment(start, heard[start : start + length].tolist()))

    def is_speech_detected(self) -> bool:
        return self.speech

    def empty(self) -> bool:
        return not self._segments

    @property
    def front(self) -> FakeSegment:
        return self._segments[0]

    def accept_waveform(self, samples: np.ndarray) -> None:
        self.accepted.append(samples.copy())
        self._release()

    def pop(self) -> None:
        self._segments.pop(0)

    def flush(self) -> None:
        self.did_flush = True
        self._ranges.extend(self._flushed)
        self._flushed.clear()
        self._release()


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
    vad = FakeVad(active=[(1600, 416000)], flushed=[(424000, 4000)])
    sherpa = FakeSherpa(vad)
    monkeypatch.setitem(sys.modules, "sherpa_onnx", sherpa)
    segmenter = PhraseSegmenter("mic", Path("silero_vad.onnx"))

    active_phrases = segmenter.accept(np.zeros(428000, dtype=np.float32))
    final_phrases = segmenter.flush()

    assert sherpa.config is not None
    assert sherpa.config.silero_vad.threshold == 0.3
    assert sherpa.config.silero_vad.min_speech_duration == 0.25
    assert sherpa.config.silero_vad.min_silence_duration == 0.6
    assert sherpa.config.silero_vad.max_speech_duration == 25
    assert sherpa.config.sample_rate == 16000
    assert sherpa.config.num_threads == 1
    assert sherpa.config.provider == "cpu"
    assert max(map(len, vad.accepted)) <= 512
    assert sum(map(len, vad.accepted)) == 428000
    assert vad.did_flush is True
    assert len(active_phrases) == 2
    for phrase, (start, end) in zip(active_phrases, [(0.1, 25.1), (25.1, 26.1)], strict=True):
        assert phrase.start == pytest.approx(start)
        assert phrase.end == pytest.approx(end)
    assert len(final_phrases) == 1
    assert final_phrases[0].start == pytest.approx(26.5)
    assert final_phrases[0].end == pytest.approx(26.75)
    assert [phrase.samples.size for phrase in active_phrases] == [400000, 16000]
    assert final_phrases[0].samples.size == 4000
    phrases = (*active_phrases, *final_phrases)
    assert all(isinstance(phrase, Phrase) and phrase.source == "mic" for phrase in phrases)
    assert all(phrase.samples.dtype == np.float32 for phrase in (*active_phrases, *final_phrases))
    assert segmenter.flush() == []


def test_a_quiet_input_reaches_the_target_level_without_exceeding_gain_50():
    # A steady quiet tone at RMS 0.004: 25x gain lifts it to RMS 0.1 at once.
    quiet = np.full(512, 0.004, dtype=np.float32)
    scaled, peak = detector_gain(quiet, 0.002)

    assert peak == pytest.approx(0.004)
    assert np.sqrt(np.mean(scaled**2)) == pytest.approx(0.1, rel=1e-4)

    # RMS 0.0001 would need 1000x: the gain stops at 50x.
    faint = np.full(512, 0.0001, dtype=np.float32)
    scaled, peak = detector_gain(faint, 0.002)
    assert peak == pytest.approx(0.002)
    assert np.sqrt(np.mean(scaled**2)) == pytest.approx(0.005, rel=1e-4)


def test_a_loud_input_is_not_amplified_and_the_output_stays_within_one():
    loud = np.tile(np.array([0.9, -0.9], dtype=np.float32), 256)
    scaled, peak = detector_gain(loud, 0.002)

    assert peak == pytest.approx(0.9)
    assert np.max(np.abs(scaled)) <= np.max(np.abs(loud))
    assert np.sqrt(np.mean(scaled**2)) == pytest.approx(0.1, rel=1e-4)

    # A quiet window right after a loud one does not get the full gain: the
    # peak decays with a 10 s half-life, 0.9 * 0.5 ** (0.032 / 10) per window.
    quiet = np.full(512, 0.004, dtype=np.float32)
    scaled, peak = detector_gain(quiet, 0.9)
    assert peak == pytest.approx(0.9 * 0.5 ** (512 / 16000 / 10))
    assert np.max(np.abs(scaled)) < 0.004 * 1.0001


def test_the_gain_state_continues_across_accept_calls(monkeypatch):
    # Loud audio and then quiet audio in separate blocks of odd sizes: the
    # running peak carries over, so the quiet audio is not lifted at once.
    vad = FakeVad(active=[], flushed=[])
    monkeypatch.setitem(sys.modules, "sherpa_onnx", FakeSherpa(vad))
    segmenter = PhraseSegmenter("mic", Path("silero_vad.onnx"))

    segmenter.accept(np.full(700, 0.5, dtype=np.float32))
    segmenter.accept(np.full(324, 0.5, dtype=np.float32))
    segmenter.accept(np.full(1000, 0.01, dtype=np.float32))
    segmenter.accept(np.full(536, 0.01, dtype=np.float32))
    segmenter.flush()

    # One gain update for each whole 512-sample window across the calls.
    assert [len(window) for window in vad.accepted] == [512] * 5
    assert vad.accepted[0] == pytest.approx(np.full(512, 0.1), rel=1e-4)
    peak = 0.5 * (0.5 ** (512 / 16000 / 10)) ** 3
    assert vad.accepted[4] == pytest.approx(np.full(512, 0.01 * 0.1 / peak), rel=1e-4)


def test_phrases_hold_the_original_samples_while_the_detector_hears_the_gain(monkeypatch):
    vad = FakeVad(active=[(512, 1024)], flushed=[(2048, 1000)])
    monkeypatch.setitem(sys.modules, "sherpa_onnx", FakeSherpa(vad))
    segmenter = PhraseSegmenter("mic", Path("silero_vad.onnx"))
    rng = np.random.default_rng(3)
    audio = (rng.standard_normal(3048) * 0.002).astype(np.float32)

    phrases = segmenter.accept(audio[:1500])
    phrases += segmenter.accept(audio[1500:])
    phrases += segmenter.flush()

    heard = np.concatenate(vad.accepted)
    assert heard.size == audio.size
    assert np.sqrt(np.mean(heard**2)) > 10 * np.sqrt(np.mean(audio**2))
    assert [(phrase.start, phrase.samples.size) for phrase in phrases] == [
        (512 / 16000, 1024),
        (2048 / 16000, 1000),
    ]
    assert np.array_equal(phrases[0].samples, audio[512:1536])
    assert np.array_equal(phrases[1].samples, audio[2048:3048])


def test_a_block_longer_than_the_kept_audio_keeps_its_early_phrase(monkeypatch):
    # One block of 130 s, longer than the 120 s of kept original audio, with
    # speech at 1 s: the detector queues that segment early in the feed, as
    # sherpa-onnx does, and the phrase must still hold the original samples.
    # Seen to FAIL with "VAD segment 16000+32000 is outside the kept audio"
    # while accept fed the whole block before it drained the detector.
    vad = FakeVad(active=[(16000, 32000)], flushed=[])
    monkeypatch.setitem(sys.modules, "sherpa_onnx", FakeSherpa(vad))
    segmenter = PhraseSegmenter("mic", Path("silero_vad.onnx"))
    audio = (np.random.default_rng(4).standard_normal(130 * 16000) * 0.01).astype(np.float32)

    [phrase] = segmenter.accept(audio)

    assert phrase.start == pytest.approx(1.0)
    assert np.array_equal(phrase.samples, audio[16000:48000])
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
    model_path = vad_model_path()
    audio_path = (
        Path(__file__).resolve().parents[3] / "tmp" / "live_audio" / "1-two-speakers-en.wav"
    )
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
