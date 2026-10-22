# SPDX-License-Identifier: GPL-3.0-or-later
"""Observe real stop-time relabel progress with synthetic external dependencies."""

import importlib.util
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

spec = importlib.util.spec_from_file_location(
    "session_fixture", Path.cwd() / "tests/lib/live/test_live_session.py"
)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)

with TemporaryDirectory() as directory, pytest.MonkeyPatch.context() as patch:
    session, _, _, system, recorder, _ = fixture._make_session(
        patch,
        Path(directory),
        tracker=fixture.VoiceSpeakerTracker,
        diarize_mic=os.environ.get("DIARIZE_MIC", "1") == "1",
    )
    recorder.emit(1)
    recorder.emit(4)
    system.emit(1)
    session._queue.join()
    observations = []
    original = session._set_relabel_progress

    def observe(done, total):
        original(done, total)
        observations.append(session.relabel_status)

    session._set_relabel_progress = observe
    session.stop()
    for status in observations:
        print(status)
    assert not any("0/" in status for status in observations[2:]), (
        "Progress resets after the first source is complete"
    )
