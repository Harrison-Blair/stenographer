# SPDX-License-Identifier: GPL-3.0-or-later
"""Speaker clustering tests without sherpa or audio hardware."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from stenographer.lib.live.speaker import SpeakerClustering
from stenographer.lib.live.speaker_tracker import SpeakerTracker


def test_clustering_creates_a_speaker_when_no_match_reaches_threshold():
    clustering = SpeakerClustering(threshold=0.5)

    assert clustering.assign(np.array([1.0, 0.0], dtype=np.float32)) == "speaker-1"
    assert clustering.assign(np.array([0.0, 1.0], dtype=np.float32)) == "speaker-2"


def test_clustering_joins_the_best_speaker_above_threshold():
    clustering = SpeakerClustering(threshold=0.9)
    first = np.array([1.0, 0.0], dtype=np.float32)
    close = np.array([0.99, 0.1], dtype=np.float32)

    assert clustering.assign(first) == "speaker-1"
    assert clustering.assign(close) == "speaker-1"


def test_clustering_updates_the_mean_before_a_later_decision():
    clustering = SpeakerClustering(threshold=0.82)
    first = np.array([1.0, 0.0], dtype=np.float32)
    second = np.array([0.9, 0.43589], dtype=np.float32)
    later = np.array([0.8, 0.6], dtype=np.float32)

    assert clustering.assign(first) == "speaker-1"
    assert clustering.assign(second) == "speaker-1"
    assert clustering.assign(later) == "speaker-1"


def test_clustering_never_reuses_speaker_numbers():
    clustering = SpeakerClustering(threshold=0.99)
    vectors = (
        np.array([1.0, 0.0], dtype=np.float32),
        np.array([0.0, 1.0], dtype=np.float32),
        np.array([1.0, 1.0], dtype=np.float32),
        np.array([1.0, -1.0], dtype=np.float32),
    )

    assert [clustering.assign(vector) for vector in vectors] == [
        "speaker-1",
        "speaker-2",
        "speaker-3",
        "speaker-4",
    ]


def _tracker(monkeypatch, embeddings):
    vectors = iter(embeddings)
    config_values = {}
    streams = []

    class FakeConfig:
        def __init__(self, *, model, num_threads, debug, provider):
            config_values.update(
                model=model, num_threads=num_threads, debug=debug, provider=provider
            )

    class FakeStream:
        def accept_waveform(self, *, sample_rate, waveform):
            self.sample_rate = sample_rate
            self.waveform = waveform.copy()

        def input_finished(self):
            pass

    class FakeExtractor:
        def __init__(self, config):
            self.config = config

        def create_stream(self):
            stream = FakeStream()
            streams.append(stream)
            return stream

        def is_ready(self, stream):
            return True

        def compute(self, stream):
            return next(vectors)

    monkeypatch.setitem(
        sys.modules,
        "sherpa_onnx",
        SimpleNamespace(
            SpeakerEmbeddingExtractorConfig=FakeConfig,
            SpeakerEmbeddingExtractor=FakeExtractor,
        ),
    )
    tracker = SpeakerTracker("speaker.onnx", threshold=0.5, num_threads=2)
    return tracker, config_values, streams


def test_tracker_extracts_samples_and_uses_the_default_label(monkeypatch):
    samples = np.array([0.15, -0.25, 0.4], dtype=np.float32)
    tracker, config, streams = _tracker(
        monkeypatch, [np.array([1.0, 0.0], dtype=np.float32)]
    )

    assert tracker.assign(samples) == "speaker-1"
    assert tracker.label("speaker-1") == "Speaker 1"
    assert config == {
        "model": "speaker.onnx",
        "num_threads": 2,
        "debug": False,
        "provider": "cpu",
    }
    assert streams[0].sample_rate == 16000
    np.testing.assert_array_equal(streams[0].waveform, samples)


def test_renaming_two_speakers_to_the_same_name_shares_the_label(monkeypatch):
    tracker, _, _ = _tracker(
        monkeypatch,
        [
            np.array([1.0, 0.0], dtype=np.float32),
            np.array([0.0, 1.0], dtype=np.float32),
        ],
    )
    first = tracker.assign(np.array([0.1], dtype=np.float32))
    second = tracker.assign(np.array([0.2], dtype=np.float32))

    tracker.rename(first, "Alice")
    tracker.rename(second, " Alice ")

    assert first == "speaker-1"
    assert second == "speaker-2"
    assert tracker.label(first) == "Alice"
    assert tracker.label(second) == "Alice"


def test_rename_refuses_the_mic_and_empty_names(monkeypatch):
    tracker, _, _ = _tracker(
        monkeypatch, [np.array([1.0, 0.0], dtype=np.float32)]
    )
    speaker_id = tracker.assign(np.array([0.1], dtype=np.float32))

    with pytest.raises(ValueError):
        tracker.rename("you", "Alice")
    with pytest.raises(ValueError):
        tracker.rename(speaker_id, "  \t ")
