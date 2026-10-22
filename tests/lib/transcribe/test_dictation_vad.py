# SPDX-License-Identifier: GPL-3.0-or-later
"""Dictation silence: only the VAD speech of a capture reaches the decoder."""

from __future__ import annotations

import numpy as np

from stenographer.lib.live.phrase import Phrase
from stenographer.lib.transcribe.dictation_vad import dictation_speech, keep_speech

_RATE = 16000


def _ramp(frames: int) -> np.ndarray:
    return np.arange(frames, dtype=np.float32)


def test_no_speech_region_keeps_nothing():
    kept = keep_speech(_ramp(32000), [], pad_frames=4000)
    assert kept.size == 0
    assert kept.dtype == np.float32


def test_each_region_keeps_the_pre_pad_before_it():
    samples = _ramp(48000)
    kept = keep_speech(samples, [(8000, 12000), (30000, 34000)], pad_frames=4000)
    assert kept.tolist() == [*range(4000, 12000), *range(26000, 34000)]


def test_the_pre_pad_stops_at_the_capture_start():
    kept = keep_speech(_ramp(16000), [(1000, 2000)], pad_frames=4000)
    assert kept.tolist() == list(range(0, 2000))


def test_the_pre_pad_never_repeats_the_previous_region():
    kept = keep_speech(_ramp(16000), [(5000, 6000), (7000, 8000)], pad_frames=4000)
    assert kept.tolist() == list(range(1000, 8000))


class _Segmenter:
    """Stands in for ``PhraseSegmenter``: the Silero VAD is the external dependency."""

    def __init__(self, phrases, final=()):
        self._phrases = list(phrases)
        self._final = list(final)
        self.accepted: list[np.ndarray] = []
        self.flushed = False

    def accept(self, block):
        self.accepted.append(block)
        return self._phrases

    def flush(self):
        self.flushed = True
        return self._final


def _phrase(start_frame: int, frames: int) -> Phrase:
    start = start_frame / _RATE
    return Phrase(
        source="mic",
        start=start,
        end=start + frames / _RATE,
        samples=np.zeros(frames, dtype=np.float32),
    )


def test_dictation_speech_keeps_padded_vad_regions_including_the_flushed_one():
    samples = _ramp(64000)
    segmenter = _Segmenter([_phrase(16000, 8000)], final=[_phrase(48000, 4000)])
    kept = dictation_speech(samples, "unused.onnx", segmenter_factory=lambda: segmenter)
    assert segmenter.flushed
    assert kept.tolist() == [*range(12000, 24000), *range(44000, 52000)]


def test_dictation_speech_of_a_silent_capture_is_empty():
    segmenter = _Segmenter([])
    kept = dictation_speech(
        np.zeros(32000, dtype=np.float32), "unused.onnx", segmenter_factory=lambda: segmenter
    )
    assert kept.size == 0


def test_dictation_speech_hands_the_vad_one_mono_buffer():
    stereo = np.stack([_ramp(1600), np.zeros(1600, dtype=np.float32)], axis=1)
    segmenter = _Segmenter([])
    dictation_speech(stereo, "unused.onnx", segmenter_factory=lambda: segmenter)
    [block] = segmenter.accepted
    assert block.ndim == 1
    assert block.tolist() == _ramp(1600).tolist()
