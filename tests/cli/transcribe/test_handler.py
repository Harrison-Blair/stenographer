# SPDX-License-Identifier: GPL-3.0-or-later
"""Command orchestration tests for file transcription summaries."""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile

from stenographer.cli.transcribe.handler import cmd_transcribe
from stenographer.lib.audio.constants import SAMPLE_RATE
from stenographer.lib.config.models import Config
from stenographer.lib.refine.results import RefineResult
from stenographer.lib.transcribe.results import TranscriptionResult
from stenographer.lib.transcribe.text import count_words

#: Twelve words: over the ten-word refine threshold.
SPOKEN = "um i think we should ship it on thursday no wait friday"
REFINED = "I think we should ship it on Friday."


@pytest.fixture(autouse=True)
def _vad_hears(monkeypatch):
    """The Silero VAD is the external dependency: it hears 0.1 s of speech."""
    from stenographer.lib.transcribe import dictation_vad

    monkeypatch.setattr(dictation_vad, "speech_seconds", lambda samples, model_path: 0.1)


def _wav(tmp_path):
    path = tmp_path / "clip.wav"
    soundfile.write(path, np.full(SAMPLE_RATE // 5, 0.1, dtype=np.float32), SAMPLE_RATE)
    return path


def _spoken_clip(monkeypatch, tmp_path, text: str):
    """A real WAV plus a decoder that returns *text*, so only refine is a double."""
    from stenographer.lib.transcribe import bark_download, model

    path = _wav(tmp_path)

    class ModelDouble:
        def __init__(self):
            pass

        def transcribe(self, samples):
            return TranscriptionResult(text=text, duration_seconds=samples.size / SAMPLE_RATE)

        def close(self):
            pass

    monkeypatch.setattr(bark_download, "is_model_cached", lambda: True)
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
    from stenographer.lib.transcribe import bark_download, model

    path = _wav(tmp_path)
    decode_error = RuntimeError("private decode detail")
    format_error = RuntimeError("private format detail")
    close_error = RuntimeError("cleanup detail")
    instances = []

    class FailingText(str):
        def split(self, *args, **kwargs):
            raise format_error

    class ModelDouble:
        def __init__(self):
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
            )

        def close(self):
            self.close_calls += 1
            if failure_phase:
                # Cleanup must not replace the application-owned primary error.
                raise close_error

    monkeypatch.setattr(bark_download, "is_model_cached", lambda: True)
    monkeypatch.setattr(model, "Model", ModelDouble)
    args = argparse.Namespace(file=str(path), raw=False, refine=False)

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
    assert "vad_frames=1600" in summary
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
            ("segments=", "words=", "chars_raw=", "chars_out=")
            if failure_phase == "decode"
            else ("chars_out=",)
        ):
            assert absent not in summary
        if failure_phase == "format":
            assert "chars_raw=20" in summary
        assert capsys.readouterr().out == ""
    else:
        assert "outcome=OK" in summary
        for present in ("segments=0", "words=0", "chars_raw=20", "chars_out=21"):
            assert present in summary
        assert capsys.readouterr().out == "Sensitive transcript \n"


@pytest.mark.parametrize(("speech", "outcome"), [(0.0, "SILENT"), (0.4, "OK")])
def test_the_outcome_follows_the_vad_and_the_file_is_decoded_either_way(
    speech, outcome, monkeypatch, tmp_path, caplog, capsys
):
    from stenographer.lib.transcribe import dictation_vad

    checked: list[np.ndarray] = []

    def vad(samples, model_path):
        checked.append(samples)
        return speech

    monkeypatch.setattr(dictation_vad, "speech_seconds", vad)
    path = _spoken_clip(monkeypatch, tmp_path, "hello there")
    args = argparse.Namespace(file=str(path), raw=False, refine=False)

    with caplog.at_level(logging.INFO, logger="stenographer.lib.transcribe.pipeline"):
        assert cmd_transcribe.__wrapped__(args, Config.defaults()) == 0

    [samples] = checked
    assert samples.size == SAMPLE_RATE // 5
    [summary] = [m for m in caplog.messages if m.startswith("pipeline: utterance ")]
    assert f"outcome={outcome}" in summary
    assert f"vad_frames={round(speech * SAMPLE_RATE)}" in summary
    assert capsys.readouterr().out == "Hello there \n"


def test_a_missing_file_gets_the_cannot_read_error_before_the_model_cache_is_consulted(
    monkeypatch,
    tmp_path,
    capsys,
):
    from stenographer.lib.transcribe import bark_download

    consulted: list[str] = []
    monkeypatch.setattr(bark_download, "is_model_cached", lambda: consulted.append("probe") or True)
    path = tmp_path / "absent.wav"

    args = argparse.Namespace(file=str(path), raw=False, refine=False)

    assert cmd_transcribe.__wrapped__(args, Config.defaults()) == 2

    captured = capsys.readouterr()
    assert captured.err.startswith(f"stenographer: cannot read {path}: ")
    assert captured.err.count("\n") == 1
    assert captured.out == ""
    assert consulted == []


def _ffmpeg_that_cannot_read_the_file(monkeypatch, tmp_path):
    """Put only ffmpeg and ffprobe on PATH that exit as the real ones do for damaged input."""
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    # Real ffmpeg 8 exits with 183 and ffprobe with 1 on "Invalid data found when processing input".
    for name, status in (("ffmpeg", 183), ("ffprobe", 1)):
        executable = binary_dir / name
        executable.write_text(f"#!{sys.executable}\nimport sys\nsys.exit({status})\n")
        executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(binary_dir))


def test_an_unreadable_file_is_reported_before_an_uncached_model(monkeypatch, tmp_path, capsys):
    # The real Bark probe over an empty data dir: no model installed.
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    _ffmpeg_that_cannot_read_the_file(monkeypatch, tmp_path)

    path = tmp_path / "clip.wav"
    path.write_bytes(b"RIFF not really a wave file at all")

    args = argparse.Namespace(file=str(path), raw=False, refine=False)

    assert cmd_transcribe.__wrapped__(args, Config.defaults()) == 2

    captured = capsys.readouterr()
    assert captured.err.startswith(f"stenographer: cannot read {path}: ")
    assert captured.out == ""


def test_an_uncached_model_is_refused_with_the_download_instruction(
    monkeypatch,
    tmp_path,
    capsys,
):
    # The real Bark probe over an empty data dir: no model installed. The root
    # conftest does not redirect XDG_DATA_HOME, so this test does.
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    path = _wav(tmp_path)

    args = argparse.Namespace(file=str(path), raw=False, refine=False)

    assert cmd_transcribe.__wrapped__(args, Config.defaults()) == 78

    captured = capsys.readouterr()
    assert captured.err == (
        "stenographer: ASR model not found; run `stenographer model download --asr`\n"
    )
    assert captured.out == ""


def test_audio_that_cannot_be_decoded_is_refused_with_its_path(monkeypatch, tmp_path, capsys):
    from stenographer.lib.transcribe import bark_download

    _ffmpeg_that_cannot_read_the_file(monkeypatch, tmp_path)
    path = tmp_path / "clip.wav"
    path.write_bytes(b"RIFF not really a wave file at all")
    monkeypatch.setattr(bark_download, "is_model_cached", lambda: True)

    args = argparse.Namespace(file=str(path), raw=False, refine=False)

    assert cmd_transcribe.__wrapped__(args, Config.defaults()) == 2

    captured = capsys.readouterr()
    assert captured.err == f"stenographer: cannot read {path}: ffmpeg exited with status 183\n"
    assert captured.out == ""


def test_a_damaged_wav_needs_ffmpeg_when_ffmpeg_is_missing(monkeypatch, tmp_path, capsys):
    from stenographer.lib.transcribe import bark_download

    monkeypatch.setenv("PATH", "")
    path = tmp_path / "clip.wav"
    path.write_bytes(b"RIFF not really a wave file at all")
    monkeypatch.setattr(bark_download, "is_model_cached", lambda: True)

    args = argparse.Namespace(file=str(path), raw=False, refine=False)

    assert cmd_transcribe.__wrapped__(args, Config.defaults()) == 69

    captured = capsys.readouterr()
    assert captured.err.startswith(f"stenographer: cannot read {path}: needs ffmpeg")
    assert captured.out == ""


def test_a_close_failure_surfaces_when_the_run_itself_succeeded(monkeypatch, tmp_path, caplog):
    """Seen to FAIL against a ``finally`` that swallowed ``close()`` errors: a
    leaked native handle was reported as a clean transcription."""

    from stenographer.lib.transcribe import bark_download, model

    path = _wav(tmp_path)
    close_error = RuntimeError("could not release the decoder")

    class ModelDouble:
        def __init__(self):
            pass

        def transcribe(self, samples):
            return TranscriptionResult(
                text="a clean transcript",
                duration_seconds=samples.size / SAMPLE_RATE,
            )

        def close(self):
            raise close_error

    monkeypatch.setattr(bark_download, "is_model_cached", lambda: True)
    monkeypatch.setattr(model, "Model", ModelDouble)
    args = argparse.Namespace(file=str(path), raw=False, refine=False)

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
    from stenographer.lib.transcribe import bark_download, model

    path = _wav(tmp_path)
    load_error = RuntimeError("CUDA library not found")

    def refuse():
        raise load_error

    monkeypatch.setattr(bark_download, "is_model_cached", lambda: True)
    monkeypatch.setattr(model, "Model", refuse)
    args = argparse.Namespace(file=str(path), raw=False, refine=False)

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
        return count_words(text) >= 10

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

    built: list[dict] = []
    refiner = _Refiner(REFINED)

    def build_refiner(section, *, idle_unload_seconds, enabled=None):
        built.append({"section": section, "enabled": enabled})
        return refiner

    monkeypatch.setattr(
        "stenographer.lib.refine.factory.build_refiner", build_refiner, raising=True
    )
    return SimpleNamespace(built=built, refiner=refiner)


def test_refine_flag_cleans_a_long_transcript_before_it_is_printed(
    refine_capture, monkeypatch, tmp_path, capsys
):
    path = _spoken_clip(monkeypatch, tmp_path, SPOKEN)

    assert cmd_transcribe.__wrapped__(_refine_args(path, refine=True), Config.defaults()) == 0

    assert refine_capture.refiner.calls, "the refiner was never asked"
    assert capsys.readouterr().out == f"{REFINED}\n"


def test_the_daemon_setting_is_not_inherited_by_a_file_transcription(
    refine_capture, monkeypatch, tmp_path, capsys
):
    """A configured daemon must not make one-off file runs start calling a
    model, and ``--refine`` must work against a config with the stage off."""
    defaults = Config.defaults()
    enabled_cfg = dataclasses.replace(
        defaults, refine=dataclasses.replace(defaults.refine, enabled=True)
    )
    disabled_cfg = dataclasses.replace(
        defaults, refine=dataclasses.replace(defaults.refine, enabled=False)
    )
    path = _spoken_clip(monkeypatch, tmp_path, SPOKEN)

    assert cmd_transcribe.__wrapped__(_refine_args(path), enabled_cfg) == 0

    assert refine_capture.built == [], "an enabled daemon leaked into the file path"
    assert REFINED not in capsys.readouterr().out

    assert cmd_transcribe.__wrapped__(_refine_args(path, refine=True), disabled_cfg) == 0

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
    captured = capsys.readouterr()
    assert captured.out == f"{SPOKEN}\n"
    assert "--raw skips refinement requested by --refine" in captured.err


def test_a_short_transcript_is_below_the_threshold_and_is_printed_unrefined(
    refine_capture, monkeypatch, tmp_path, capsys
):
    path = _spoken_clip(monkeypatch, tmp_path, "ship it on friday")

    assert cmd_transcribe.__wrapped__(_refine_args(path, refine=True), Config.defaults()) == 0

    assert refine_capture.refiner.calls == []
    # The formatter's dictation trailing space, unchanged by the skipped stage.
    assert capsys.readouterr().out == "Ship it on friday \n"


def test_transcribe_refine_sends_the_configured_vocabulary(ollama_wire, monkeypatch, tmp_path):
    path = _spoken_clip(monkeypatch, tmp_path, SPOKEN)
    cfg = Config.defaults()
    cfg = dataclasses.replace(
        cfg, refine=dataclasses.replace(cfg.refine, vocabulary=("Kubernetes", "PipeWire"))
    )

    assert cmd_transcribe.__wrapped__(_refine_args(path, refine=True), cfg) == 0

    assert len(ollama_wire) == 1
    wire = json.dumps(ollama_wire[0]["messages"])
    assert "Kubernetes" in wire
    assert "PipeWire" in wire


def _m4a(tmp_path):
    """Bytes that libsndfile cannot read, named like the format ffmpeg decodes."""
    path = tmp_path / "clip.m4a"
    path.write_bytes(b"not a libsndfile format")
    return path


def test_a_file_libsndfile_cannot_read_is_decoded_through_ffmpeg(monkeypatch, tmp_path, capsys):
    from stenographer.lib.platform.linux.ffmpeg_decoder import SubprocessFfmpegDecoder

    heard: list[int] = []

    def decode(self, path, *, block_frames=65536):
        yield np.full(SAMPLE_RATE // 2, 0.1, dtype=np.float32)
        yield np.full(SAMPLE_RATE // 2, 0.1, dtype=np.float32)

    monkeypatch.setattr(SubprocessFfmpegDecoder, "available", lambda self: True)
    monkeypatch.setattr(SubprocessFfmpegDecoder, "duration", lambda self, path: 1.0)
    monkeypatch.setattr(SubprocessFfmpegDecoder, "decode", decode)
    from stenographer.lib.transcribe import bark_download, model

    class ModelDouble:
        def __init__(self):
            pass

        def transcribe(self, samples):
            heard.append(samples.size)
            return TranscriptionResult(text="hello there", duration_seconds=1.0)

        def close(self):
            pass

    monkeypatch.setattr(bark_download, "is_model_cached", lambda: True)
    monkeypatch.setattr(model, "Model", ModelDouble)
    args = argparse.Namespace(file=str(_m4a(tmp_path)), raw=False, refine=False)

    assert cmd_transcribe.__wrapped__(args, Config.defaults()) == 0

    assert heard == [SAMPLE_RATE]
    assert capsys.readouterr().out == "Hello there \n"


def test_a_file_that_needs_ffmpeg_ends_with_a_clear_message_when_it_is_missing(
    monkeypatch, tmp_path, capsys
):
    from stenographer.lib.platform.linux.ffmpeg_decoder import SubprocessFfmpegDecoder
    from stenographer.lib.transcribe import bark_download

    monkeypatch.setattr(SubprocessFfmpegDecoder, "available", lambda self: False)
    monkeypatch.setattr(bark_download, "is_model_cached", lambda: True)
    path = _m4a(tmp_path)
    args = argparse.Namespace(file=str(path), raw=False, refine=False)

    assert cmd_transcribe.__wrapped__(args, Config.defaults()) == 69

    err = capsys.readouterr().err
    assert err.startswith(f"stenographer: cannot read {path}: needs ffmpeg")
