# SPDX-License-Identifier: GPL-3.0-or-later
"""Command orchestration tests for file transcription summaries."""

from __future__ import annotations

import argparse
import logging

import numpy as np
import pytest
import soundfile

from stenographer.config import Config
from stenographer.constants import SAMPLE_RATE
from stenographer.transcribe.model import TranscriptionResult


@pytest.mark.parametrize("failure_phase", [None, "decode", "format"])
def test_file_transcription_closes_and_summarizes_success_or_failure(
    failure_phase,
    monkeypatch,
    tmp_path,
    caplog,
    capsys,
):
    from stenographer.cli.commands.transcribe import cmd_transcribe
    from stenographer.transcribe import model

    path = tmp_path / "clip.wav"
    soundfile.write(path, np.full(SAMPLE_RATE // 5, 0.1, dtype=np.float32), SAMPLE_RATE)
    decode_error = RuntimeError("private decode detail")
    format_error = RuntimeError("private format detail")
    close_error = RuntimeError("cleanup detail")
    instances = []

    class FailingText(str):
        def split(self, *args, **kwargs):
            raise format_error

    class ModelDouble:
        def __init__(self, cfg):
            self.close_calls = 0
            instances.append(self)

        def transcribe(self, samples):
            if failure_phase == "decode":
                raise decode_error
            return TranscriptionResult(
                text=(
                    FailingText("sensitive transcript")
                    if failure_phase == "format"
                    else "sensitive transcript"
                ),
                duration_seconds=samples.size / SAMPLE_RATE,
                vad_seconds=0.1,
            )

        def close(self):
            self.close_calls += 1
            if failure_phase:
                # Cleanup must not replace the application-owned primary error.
                raise close_error

    monkeypatch.setattr(model, "is_model_cached", lambda name: True)
    monkeypatch.setattr(model, "Model", ModelDouble)
    args = argparse.Namespace(file=str(path), raw=False)

    with caplog.at_level(logging.INFO, logger="stenographer.transcribe.pipeline"):
        if failure_phase:
            with pytest.raises(RuntimeError) as raised:
                cmd_transcribe.__wrapped__(args, Config.defaults())
            expected = decode_error if failure_phase == "decode" else format_error
            assert raised.value is expected
        else:
            assert cmd_transcribe.__wrapped__(args, Config.defaults()) == 0

    summaries = [
        message for message in caplog.messages if message.startswith("pipeline: utterance ")
    ]
    assert len(instances) == 1
    assert instances[0].close_calls == 1
    assert len(summaries) == 1
    summary = summaries[0]
    assert "utt=0 source=file" in summary
    assert "out_frames=3200" in summary
    assert "gate=pass" in summary
    assert "cold=1" in summary
    assert "load_ms=" in summary
    assert "decode_ms=" in summary
    assert "total_ms=" in summary
    assert "sensitive transcript" not in summary
    assert "private decode detail" not in summary
    assert "private format detail" not in summary
    assert "cleanup detail" not in summary

    if failure_phase:
        assert "outcome=ERROR" in summary
        for absent in ("vad_frames=", "segments=", "words=", "chars_raw=", "chars_out="):
            assert absent not in summary
        assert capsys.readouterr().out == ""
    else:
        assert "outcome=OK" in summary
        for present in ("vad_frames=1600", "segments=0", "words=0", "chars_raw=20", "chars_out=21"):
            assert present in summary
        assert capsys.readouterr().out == "Sensitive transcript \n"
