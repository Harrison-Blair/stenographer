# SPDX-License-Identifier: GPL-3.0-or-later
"""The bundled model and the use of the library's pass, with the library as a stand-in."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from stenographer.lib.live.speech_pieces import find_speech_pieces, segmentation_model_path

SAMPLES = np.zeros(16000, np.float32)


class Result:
    def __init__(self, segments):
        self._segments = segments

    def sort_by_start_time(self):
        return sorted(self._segments, key=lambda segment: segment.start)


def fake_library(monkeypatch, process):
    """Stand in for ``sherpa_onnx`` and record the config of the pass."""
    configs = []

    class Diarization:
        def __init__(self, config):
            configs.append(config)

        def process(self, samples, callback):
            return process(samples, callback)

    library = SimpleNamespace(
        OfflineSpeakerDiarization=Diarization,
        OfflineSpeakerDiarizationConfig=lambda **options: options,
        OfflineSpeakerSegmentationModelConfig=lambda **options: options,
        OfflineSpeakerSegmentationPyannoteModelConfig=lambda **options: options,
        SpeakerEmbeddingExtractorConfig=lambda **options: options,
        FastClusteringConfig=lambda **options: options,
    )
    monkeypatch.setitem(sys.modules, "sherpa_onnx", library)
    return configs


def segment(start, end):
    return SimpleNamespace(start=start, end=end, speaker=0)


def find(progress=lambda _fraction: None, should_cancel=lambda: False):
    return find_speech_pieces(
        SAMPLES, Path("speaker.onnx"), progress=progress, should_cancel=should_cancel
    )


def test_the_bundled_model_is_the_full_model_the_user_chose():
    content = segmentation_model_path().read_bytes()

    assert len(content) == 5_992_913
    assert hashlib.sha256(content).hexdigest() == (
        "220ad67ca923bef2fa91f2390c786097bf305bceb5e261d4af67b38e938e1079"
    )


def test_the_pass_uses_the_tested_settings(monkeypatch):
    configs = fake_library(monkeypatch, lambda _samples, _callback: Result([]))

    find()

    config = configs[0]
    assert config["segmentation"]["pyannote"]["model"] == str(segmentation_model_path())
    assert config["segmentation"]["num_threads"] == 2
    assert config["embedding"] == {"model": "speaker.onnx", "num_threads": 2}
    assert config["clustering"] == {"num_clusters": -1, "threshold": 0.9}
    assert (config["min_duration_on"], config["min_duration_off"]) == (0.3, 0.5)


def test_pieces_of_half_a_second_or_more_stay_in_time_order(monkeypatch):
    found = [segment(4.0, 4.5), segment(0.0, 0.49), segment(1.0, 3.0)]
    fake_library(monkeypatch, lambda _samples, _callback: Result(found))

    assert find() == ((1.0, 3.0), (4.0, 4.5))


def test_no_speech_gives_no_pieces(monkeypatch):
    fake_library(monkeypatch, lambda _samples, _callback: Result([]))

    assert find() == ()


def test_progress_reports_the_share_of_the_pass(monkeypatch):
    def process(_samples, callback):
        callback(1, 4)
        callback(4, 4)
        return Result([])

    fake_library(monkeypatch, process)
    seen = []

    find(progress=seen.append)

    assert seen == [0.25, 1.0]


def test_a_cancel_stops_the_library_at_its_next_callback(monkeypatch):
    calls = []

    def process(_samples, callback):
        for done in range(1, 6):
            calls.append(done)
            callback(done, 5)
        return Result([segment(0.0, 9.0)])

    fake_library(monkeypatch, process)

    assert find(should_cancel=lambda: len(calls) >= 2) is None
    assert calls == [1, 2]


def test_an_error_of_the_library_is_not_a_cancel(monkeypatch):
    def process(_samples, _callback):
        raise RuntimeError("Where node failed")

    fake_library(monkeypatch, process)

    with pytest.raises(RuntimeError, match="Where node failed"):
        find()
