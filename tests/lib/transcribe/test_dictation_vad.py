# SPDX-License-Identifier: GPL-3.0-or-later
"""Dictation silence: the VAD decides whether a capture holds speech."""

from __future__ import annotations

import numpy as np

from stenographer.lib.live.phrase_segmenter import Phrase
from stenographer.lib.transcribe.dictation_vad import speech_seconds

_RATE = 16000


def _ramp(frames: int) -> np.ndarray:
    return np.arange(frames, dtype=np.float32)


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


def test_speech_seconds_count_every_vad_phrase_including_the_flushed_one():
    segmenter = _Segmenter([_phrase(16000, 8000)], final=[_phrase(48000, 4000)])
    seconds = speech_seconds(_ramp(64000), "unused.onnx", segmenter_factory=lambda: segmenter)
    assert segmenter.flushed
    assert seconds == 0.75


def test_a_silent_capture_has_no_speech_seconds():
    segmenter = _Segmenter([])
    seconds = speech_seconds(
        np.zeros(32000, dtype=np.float32), "unused.onnx", segmenter_factory=lambda: segmenter
    )
    assert seconds == 0.0


def test_speech_seconds_hand_the_vad_channel_zero_as_one_mono_buffer():
    stereo = np.stack([_ramp(1600), np.zeros(1600, dtype=np.float32)], axis=1)
    segmenter = _Segmenter([])
    speech_seconds(stereo, "unused.onnx", segmenter_factory=lambda: segmenter)
    [block] = segmenter.accepted
    assert block.ndim == 1
    assert block.tolist() == _ramp(1600).tolist()
