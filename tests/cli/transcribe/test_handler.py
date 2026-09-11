# SPDX-License-Identifier: GPL-3.0-or-later
"""Command orchestration tests for file transcription summaries."""

from __future__ import annotations

import argparse
import dataclasses
import logging
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile

from stenographer.cli.transcribe.handler import cmd_transcribe
from stenographer.lib.audio.constants import SAMPLE_RATE
from stenographer.lib.config.models import Config
from stenographer.lib.refine.policy import should_refine
from stenographer.lib.refine.results import RefineResult
from stenographer.lib.transcribe.results import TranscriptionResult

#: Twelve words: over the ten-word refine threshold.
SPOKEN = "um i think we should ship it on thursday no wait friday"
REFINED = "I think we should ship it on Friday."


def _spoken_clip(monkeypatch, tmp_path, text: str):
    """A real WAV plus a decoder that returns *text*, so only refine is a double."""
    from stenographer.lib.transcribe import download, model

    path = tmp_path / "clip.wav"
    soundfile.write(path, np.full(SAMPLE_RATE // 5, 0.1, dtype=np.float32), SAMPLE_RATE)

    class ModelDouble:
        def __init__(self, cfg):
            pass

        def transcribe(self, samples):
            return TranscriptionResult(
                text=text, duration_seconds=samples.size / SAMPLE_RATE, vad_seconds=0.1
            )

        def close(self):
            pass

    monkeypatch.setattr(download, "is_model_cached", lambda name: True)
    monkeypatch.setattr(model, "Model", ModelDouble)
    return path


@pytest.mark.parametrize("failure_phase", [None, "decode", "format"])
def test_file_transcription_closes_and_summarizes_success_or_failure(
    failure_phase,
    monkeypatch,
    tmp_path,
    caplog,
    capsys,
):
    from stenographer.cli.transcribe.handler import cmd_transcribe
    from stenographer.lib.transcribe import download, model

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

    monkeypatch.setattr(download, "is_model_cached", lambda name: True)
    monkeypatch.setattr(model, "Model", ModelDouble)
    args = argparse.Namespace(file=str(path), raw=False)

    with caplog.at_level(logging.INFO, logger="stenographer.lib.transcribe.pipeline"):
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
        for absent in (
            ("vad_frames=", "segments=", "words=", "chars_raw=", "chars_out=")
            if failure_phase == "decode"
            else ("chars_out=",)
        ):
            assert absent not in summary
        if failure_phase == "format":
            assert "chars_raw=20" in summary
            assert "vad_frames=1600" in summary
        assert capsys.readouterr().out == ""
    else:
        assert "outcome=OK" in summary
        for present in ("vad_frames=1600", "segments=0", "words=0", "chars_raw=20", "chars_out=21"):
            assert present in summary
        assert capsys.readouterr().out == "Sensitive transcript \n"


def test_a_missing_file_is_refused_before_the_model_cache_is_consulted(
    monkeypatch,
    tmp_path,
    capsys,
):
    from stenographer.cli.transcribe.handler import cmd_transcribe
    from stenographer.lib.transcribe import download

    consulted: list[str] = []
    monkeypatch.setattr(download, "is_model_cached", lambda name: consulted.append(name) or True)
    path = tmp_path / "absent.wav"

    args = argparse.Namespace(file=str(path), raw=False)

    assert cmd_transcribe.__wrapped__(args, Config.defaults()) == 2

    captured = capsys.readouterr()
    assert captured.err == f"stenographer: file not found: {path}\n"
    assert captured.out == ""
    assert consulted == []


def test_an_uncached_model_is_refused_with_the_download_instruction(
    monkeypatch,
    tmp_path,
    capsys,
):
    from stenographer.cli.transcribe.handler import cmd_transcribe
    from stenographer.lib.transcribe import download

    path = tmp_path / "clip.wav"
    soundfile.write(path, np.full(SAMPLE_RATE // 5, 0.1, dtype=np.float32), SAMPLE_RATE)
    monkeypatch.setattr(download, "is_model_cached", lambda name: False)

    args = argparse.Namespace(file=str(path), raw=False)

    assert cmd_transcribe.__wrapped__(args, Config.defaults()) == 78

    captured = capsys.readouterr()
    assert captured.err == (
        "stenographer: ASR model not found; run `stenographer model download`\n"
    )
    assert captured.out == ""


def test_audio_that_cannot_be_decoded_is_refused_with_its_path(monkeypatch, tmp_path, capsys):
    from stenographer.cli.transcribe.handler import cmd_transcribe
    from stenographer.lib.transcribe import download

    path = tmp_path / "clip.wav"
    path.write_bytes(b"RIFF not really a wave file at all")
    monkeypatch.setattr(download, "is_model_cached", lambda name: True)

    args = argparse.Namespace(file=str(path), raw=False)

    assert cmd_transcribe.__wrapped__(args, Config.defaults()) == 2

    captured = capsys.readouterr()
    assert captured.err.startswith(f"stenographer: cannot read {path}: ")
    assert captured.out == ""


def test_a_close_failure_surfaces_when_the_run_itself_succeeded(monkeypatch, tmp_path, caplog):
    """Seen to FAIL against a ``finally`` that swallowed ``close()`` errors: a
    leaked native handle was reported as a clean transcription."""

    from stenographer.cli.transcribe.handler import cmd_transcribe
    from stenographer.lib.transcribe import download, model

    path = tmp_path / "clip.wav"
    soundfile.write(path, np.full(SAMPLE_RATE // 5, 0.1, dtype=np.float32), SAMPLE_RATE)
    close_error = RuntimeError("could not release the decoder")

    class ModelDouble:
        def __init__(self, cfg):
            pass

        def transcribe(self, samples):
            return TranscriptionResult(
                text="a clean transcript",
                duration_seconds=samples.size / SAMPLE_RATE,
                vad_seconds=0.1,
            )

        def close(self):
            raise close_error

    monkeypatch.setattr(download, "is_model_cached", lambda name: True)
    monkeypatch.setattr(model, "Model", ModelDouble)
    args = argparse.Namespace(file=str(path), raw=False)

    with (
        caplog.at_level(logging.INFO, logger="stenographer.lib.transcribe.pipeline"),
        pytest.raises(RuntimeError) as raised,
    ):
        cmd_transcribe.__wrapped__(args, Config.defaults())

    assert raised.value is close_error
    # The summary is still written: the run's own measurements are not lost.
    summaries = [
        message for message in caplog.messages if message.startswith("pipeline: utterance ")
    ]
    assert len(summaries) == 1
    assert "outcome=OK" in summaries[0]
    assert "a clean transcript" not in summaries[0]


def test_a_model_that_never_loads_is_summarized_without_a_close(monkeypatch, tmp_path, caplog):
    from stenographer.cli.transcribe.handler import cmd_transcribe
    from stenographer.lib.transcribe import download, model

    path = tmp_path / "clip.wav"
    soundfile.write(path, np.full(SAMPLE_RATE // 5, 0.1, dtype=np.float32), SAMPLE_RATE)
    load_error = RuntimeError("CUDA library not found")

    def refuse(cfg):
        raise load_error

    monkeypatch.setattr(download, "is_model_cached", lambda name: True)
    monkeypatch.setattr(model, "Model", refuse)
    args = argparse.Namespace(file=str(path), raw=False)

    with (
        caplog.at_level(logging.INFO, logger="stenographer.lib.transcribe.pipeline"),
        pytest.raises(RuntimeError) as raised,
    ):
        cmd_transcribe.__wrapped__(args, Config.defaults())

    assert raised.value is load_error
    summaries = [
        message for message in caplog.messages if message.startswith("pipeline: utterance ")
    ]
    assert len(summaries) == 1
    assert "outcome=ERROR" in summaries[0]
    assert "load_ms=" in summaries[0]
    assert "decode_ms=" not in summaries[0]


class _Refiner:
    """Refiner double for the file path: the real contract, no Ollama."""

    def __init__(self, refined: str) -> None:
        self._refined = refined
        self.calls: list[str] = []
        self.last_result = RefineResult("applied", chars_in=0, chars_out=0, duration_ms=3.0)

    def will_refine(self, text: str) -> bool:
        return should_refine(text, 10)

    def refine(self, text: str) -> str:
        self.calls.append(text)
        return self._refined


def _refine_args(path, **overrides) -> argparse.Namespace:
    state = {"file": str(path), "raw": False, "refine": False}
    state.update(overrides)
    return argparse.Namespace(**state)


@pytest.fixture
def refine_capture(monkeypatch):
    """Capture how ``transcribe`` builds its refiner, without a network."""

    from stenographer.cli.transcribe import handler

    built: list[dict] = []
    refiner = _Refiner(REFINED)

    def build_refiner(section, *, idle_unload_seconds, enabled=None):
        built.append({"section": section, "enabled": enabled})
        return refiner

    monkeypatch.setattr(
        "stenographer.lib.refine.factory.build_refiner", build_refiner, raising=True
    )
    assert handler is not None
    return SimpleNamespace(built=built, refiner=refiner)


def test_refine_flag_cleans_a_long_transcript_before_it_is_printed(
    refine_capture, monkeypatch, tmp_path, capsys
):
    path = _spoken_clip(monkeypatch, tmp_path, SPOKEN)

    assert cmd_transcribe.__wrapped__(_refine_args(path, refine=True), Config.defaults()) == 0

    assert refine_capture.refiner.calls, "the refiner was never asked"
    assert capsys.readouterr().out == f"{REFINED}\n"


def test_without_the_flag_the_model_is_never_contacted(
    refine_capture, monkeypatch, tmp_path, capsys
):
    path = _spoken_clip(monkeypatch, tmp_path, SPOKEN)

    assert cmd_transcribe.__wrapped__(_refine_args(path), Config.defaults()) == 0

    assert refine_capture.built == []
    assert refine_capture.refiner.calls == []
    assert REFINED not in capsys.readouterr().out


def test_the_daemon_setting_is_not_inherited_by_a_file_transcription(
    refine_capture, monkeypatch, tmp_path, capsys
):
    """A configured daemon must not make one-off file runs start calling a
    model, and ``--refine`` must work against a config with the stage off."""
    defaults = Config.defaults()
    enabled_cfg = dataclasses.replace(
        defaults, refine=dataclasses.replace(defaults.refine, enabled=True)
    )
    path = _spoken_clip(monkeypatch, tmp_path, SPOKEN)

    assert cmd_transcribe.__wrapped__(_refine_args(path), enabled_cfg) == 0

    assert refine_capture.built == [], "an enabled daemon leaked into the file path"
    assert REFINED not in capsys.readouterr().out

    assert cmd_transcribe.__wrapped__(_refine_args(path, refine=True), defaults) == 0

    assert defaults.refine.enabled is False
    assert [entry["enabled"] for entry in refine_capture.built] == [True]


def test_raw_output_is_never_refined(refine_capture, monkeypatch, tmp_path, capsys):
    """``--raw`` means exactly what the decoder produced; a cleanup pass on top
    of it would make the flag a lie."""
    path = _spoken_clip(monkeypatch, tmp_path, SPOKEN)

    assert (
        cmd_transcribe.__wrapped__(_refine_args(path, raw=True, refine=True), Config.defaults())
        == 0
    )

    assert refine_capture.built == []
    assert refine_capture.refiner.calls == []
    assert capsys.readouterr().out == f"{SPOKEN}\n"


def test_a_short_transcript_is_below_the_threshold_and_is_printed_unrefined(
    refine_capture, monkeypatch, tmp_path, capsys
):
    path = _spoken_clip(monkeypatch, tmp_path, "ship it on friday")

    assert cmd_transcribe.__wrapped__(_refine_args(path, refine=True), Config.defaults()) == 0

    assert refine_capture.refiner.calls == []
    # The formatter's dictation trailing space, unchanged by the skipped stage.
    assert capsys.readouterr().out == "Ship it on friday \n"
