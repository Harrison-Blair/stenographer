# SPDX-License-Identifier: GPL-3.0-or-later
"""The bundled model, the use of the library, and the child process of the pass."""

from __future__ import annotations

import hashlib
import multiprocessing
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from stenographer.lib.live import speech_pieces
from stenographer.lib.live.errors import SpeechPassError
from stenographer.lib.live.speech_pieces import (
    find_speech_pieces,
    run_pass,
    segmentation_model_path,
)
from tests.support import wait_until

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


def find(progress=lambda _fraction: None):
    return run_pass(SAMPLES, "speaker.onnx", progress)


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


def test_an_error_of_the_library_reaches_the_caller(monkeypatch):
    def process(_samples, _callback):
        raise RuntimeError("Where node failed")

    fake_library(monkeypatch, process)

    with pytest.raises(RuntimeError, match="Where node failed"):
        find()


# Real child processes. The functions below run in the child, so they are at module level.


def _child_gives_pieces(audio, results, speaker_model):
    samples = np.frombuffer(audio.recv_bytes(), dtype=np.float32)
    results.send(("progress", 0.5))
    results.send(("pieces", ((float(samples.size), float(samples[-1])), (0.0, len(speaker_model)))))


def _child_runs_forever(audio, results, _speaker_model):
    audio.recv_bytes()
    results.send(("progress", 0.1))
    time.sleep(120)


def _child_holds_all_threads(_audio, results, _speaker_model):
    """Stand in for the blocked span of the library: it gives no progress."""
    results.send(("progress", 0.1))
    os.kill(os.getpid(), signal.SIGSTOP)


def _child_is_killed(_audio, _results, _speaker_model):
    os.kill(os.getpid(), signal.SIGKILL)


def _child_reports_a_failure(_audio, results, _speaker_model):
    results.send(("failed", "RuntimeError"))


def _use_child(monkeypatch, child):
    monkeypatch.setattr(speech_pieces, "_child_main", child)


def _children():
    return multiprocessing.active_children()


def test_a_child_gets_all_samples_and_returns_its_pieces_and_progress(monkeypatch):
    _use_child(monkeypatch, _child_gives_pieces)
    samples = np.linspace(0.0, 1.0, 200_000, dtype=np.float32)
    seen = []

    pieces = find_speech_pieces(
        samples, Path("speaker.onnx"), progress=seen.append, should_cancel=lambda: False
    )

    assert pieces == ((200_000.0, 1.0), (0.0, 12))
    assert seen == [0.5]
    assert _children() == []


@pytest.mark.parametrize("child", [_child_runs_forever, _child_holds_all_threads])
def test_a_cancel_kills_the_child_at_once_and_leaves_no_child(monkeypatch, child):
    _use_child(monkeypatch, child)
    seen = []
    cancelled_at = []

    def should_cancel():
        if seen and not cancelled_at:
            cancelled_at.append(time.monotonic())
        return bool(cancelled_at)

    result = find_speech_pieces(
        np.zeros(1000, np.float32),
        Path("speaker.onnx"),
        progress=seen.append,
        should_cancel=should_cancel,
    )

    assert result is None
    assert time.monotonic() - cancelled_at[0] < 1.0
    assert _children() == []


def test_a_child_that_is_killed_is_a_failed_pass(monkeypatch):
    _use_child(monkeypatch, _child_is_killed)

    with pytest.raises(SpeechPassError, match="exit code -9"):
        find_speech_pieces(
            np.zeros(1000, np.float32),
            Path("speaker.onnx"),
            progress=lambda _fraction: None,
            should_cancel=lambda: False,
        )

    assert _children() == []


def test_a_child_that_dies_before_it_reads_a_long_source_is_a_failed_pass(monkeypatch):
    _use_child(monkeypatch, _child_is_killed)

    # More samples than a pipe buffer holds, so the sender is still writing.
    with pytest.raises(SpeechPassError):
        find_speech_pieces(
            np.zeros(5_000_000, np.float32),
            Path("speaker.onnx"),
            progress=lambda _fraction: None,
            should_cancel=lambda: False,
        )


def test_a_failure_in_the_child_is_a_failed_pass_with_its_type(monkeypatch):
    _use_child(monkeypatch, _child_reports_a_failure)

    with pytest.raises(SpeechPassError, match="RuntimeError"):
        find_speech_pieces(
            np.zeros(1000, np.float32),
            Path("speaker.onnx"),
            progress=lambda _fraction: None,
            should_cancel=lambda: False,
        )

    assert _children() == []


def _child_with_a_long_pass(audio, results, speaker_model):
    """Run the real child with a pass that never ends."""

    def endless_pass(_samples, _speaker_model, progress):
        progress(0.1)
        time.sleep(120)

    speech_pieces.run_pass = endless_pass
    speech_pieces._child_main(audio, results, speaker_model)


def _parent_that_is_killed():
    """Run in its own process: start a pass, print the pid of the child, and die."""
    speech_pieces._child_main = _child_with_a_long_pass

    def report_and_die(_fraction):
        print(multiprocessing.active_children()[0].pid, flush=True)
        os.kill(os.getpid(), signal.SIGKILL)

    find_speech_pieces(
        np.zeros(1000, np.float32),
        Path("speaker.onnx"),
        progress=report_and_die,
        should_cancel=lambda: False,
    )


def test_a_child_ends_itself_when_its_parent_is_killed():
    code = (
        "from tests.lib.live.test_speech_pieces import _parent_that_is_killed\n"
        "_parent_that_is_killed()\n"
    )
    parent = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False
    )
    pid = int(parent.stdout)

    def gone():
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        return False

    try:
        assert wait_until(gone, timeout=5)
    finally:
        if not gone():
            os.kill(pid, signal.SIGKILL)
