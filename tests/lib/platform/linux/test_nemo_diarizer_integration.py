# SPDX-License-Identifier: GPL-3.0-or-later
"""The real NeMo-Speech runtime and speaker model in the real helper process.

Opt-in (``STENOGRAPHER_INTEGRATION=1``). The speech tests read a local recording
named by ``STENOGRAPHER_SPEAKER_AUDIO`` (for example a session's ``mic.flac``),
90 s from ``STENOGRAPHER_SPEAKER_AUDIO_START`` seconds, which must hold at least
two speakers; no recording is in the repository.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
import soundfile

from stenographer.lib.platform.linux.nemo_diarizer import NemoSpeakerDiarizer
from stenographer.lib.platform.linux.nemo_speech import model_path

pytestmark = pytest.mark.integration

RATE = 16000
PUSH = RATE // 10


@pytest.fixture
def diarizer():
    assert model_path().is_file(), "run scripts/fetch_speaker_model.py first"
    diarizer = NemoSpeakerDiarizer(threads=2)
    assert diarizer.unavailable_reason() is None
    yield diarizer
    diarizer.close()


@pytest.fixture
def speech() -> np.ndarray:
    path = os.environ.get("STENOGRAPHER_SPEAKER_AUDIO")
    if not path:
        pytest.skip("STENOGRAPHER_SPEAKER_AUDIO names no recording")
    start = int(float(os.environ.get("STENOGRAPHER_SPEAKER_AUDIO_START", "0")) * RATE)
    samples, rate = soundfile.read(Path(path), dtype="float32", start=start, frames=RATE * 90)
    assert rate == RATE and samples.ndim == 1
    return samples


def _run_live(diarizer, samples, *, poll: bool):
    stream = diarizer.open_live("mic")
    finals = []
    try:
        for start in range(0, len(samples), PUSH):
            stream.push(samples[start : start + PUSH])
            if poll:
                final, _ = stream.poll()
                finals.extend(final)
        finals.extend(stream.finish(timeout=300))
    finally:
        stream.close()
    return finals


def test_final_live_segments_never_change(diarizer, speech) -> None:
    polled = _run_live(diarizer, speech, poll=True)
    whole = _run_live(diarizer, speech, poll=False)

    assert len({segment.speaker for segment in whole}) >= 2
    assert sorted(polled, key=lambda s: (s.start, s.speaker)) == sorted(
        whole, key=lambda s: (s.start, s.speaker)
    )


def test_file_and_samples_give_the_same_segments(diarizer, speech, tmp_path) -> None:
    path = tmp_path / "speech.wav"
    soundfile.write(path, speech, RATE, subtype="FLOAT")

    from_file = diarizer.diarize_file(path)

    assert from_file == diarizer.diarize_file(speech)
    assert len({segment.speaker for segment in from_file}) >= 2
    assert [s.start for s in from_file] == sorted(s.start for s in from_file)


def test_silence_and_tiny_audio_give_no_segments_and_no_failure(diarizer) -> None:
    assert diarizer.diarize_file(np.zeros(RATE * 5, np.float32)) == ()
    assert diarizer.diarize_file(np.zeros(RATE // 20, np.float32)) == ()
    stream = diarizer.open_live("system")
    stream.push(np.zeros(RATE // 20, np.float32))
    assert stream.finish(timeout=60) == ()
    stream.close()


def test_two_live_streams_share_one_helper(diarizer, speech) -> None:
    mic = diarizer.open_live("mic")
    system = diarizer.open_live("system")
    pid = diarizer.pid
    for start in range(0, RATE * 20, PUSH):
        mic.push(speech[start : start + PUSH])
        system.push(np.zeros(PUSH, np.float32))
    assert mic.finish(timeout=120)
    assert system.finish(timeout=120) == ()
    assert diarizer.pid == pid
    mic.close()
    system.close()


def test_a_dead_helper_fails_open_streams(diarizer) -> None:
    stream = diarizer.open_live("mic")
    os.kill(diarizer.pid, 9)

    with pytest.raises(Exception, match="ended"):
        stream.finish(timeout=30)
