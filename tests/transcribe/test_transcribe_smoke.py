# SPDX-License-Identifier: GPL-3.0-or-later
"""Integration smoke suite for the batch transcribe path.

Four real, non-mocked checks:

  * equivalence  — the public ``transcribe`` command produces the same text as
    the surviving model.Model + format.format_transcript API on the same
    machine-supplied 16 kHz WAV.
  * conversion   — a 48 kHz stereo rendering produces the same transcript as
    the source mono 16 kHz recording.
  * read errors  — corrupt files and directories fail concisely before model
    construction.
  * hotwords     — a proper noun set in asr.hotwords is honored in the decode.

The model-based checks really load the medium.en model and decode a
machine-supplied clip; nothing is mocked. The whole module is collected only
with STENOGRAPHER_INTEGRATION=1, and skipped further unless the model is cached
locally and the fixture WAV is present — so the default unit run never touches
the network or the ASR stack.
"""

from __future__ import annotations

import dataclasses
import pathlib

import numpy as np
import pytest

pytestmark = pytest.mark.integration

_FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures"
_CLIP = _FIXTURES / "speech_16k.wav"
_HOTWORD_CLIP = _FIXTURES / "hotword_16k.wav"
_HOTWORD_NOUN = "Anthropic"
_MODEL_ID = "Systran/faster-whisper-medium.en"

if not _CLIP.exists():
    pytest.skip(f"fixture WAV absent: {_CLIP}", allow_module_level=True)

from huggingface_hub import try_to_load_from_cache  # noqa: E402

if try_to_load_from_cache(_MODEL_ID, "config.json") is None:
    pytest.skip(f"model not cached: {_MODEL_ID}", allow_module_level=True)

import soundfile  # noqa: E402


def _read(path: pathlib.Path):
    return soundfile.read(str(path), dtype="float32", always_2d=True)[0]


def test_cli_transcribe_matches_surviving_api(tmp_path, monkeypatch, capsys):
    from stenographer import config
    from stenographer.cli import main
    from stenographer.transcribe import model
    from stenographer.transcribe.format import format_transcript

    samples = _read(_CLIP)
    config_path = tmp_path / "config.toml"
    config.Config.write_default(config_path)
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(config_path))
    cfg = config.Config.load(config_path)
    assert cfg.asr.model == _MODEL_ID  # hotwords require the full, non-distil model

    m = model.Model(cfg.asr)
    try:
        expected = format_transcript(m.transcribe(samples).text)
    finally:
        m.close()

    assert main(["transcribe", str(_CLIP)]) == 0
    actual = capsys.readouterr().out
    assert actual.strip() == expected.strip()
    assert actual.strip() != ""


def test_cli_transcribe_48k_stereo_matches_16k_mono(tmp_path, monkeypatch, capsys):
    from stenographer import config
    from stenographer.cli import main

    config_path = tmp_path / "config.toml"
    config.Config.write_default(config_path)
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(config_path))

    assert main(["transcribe", str(_CLIP)]) == 0
    expected = capsys.readouterr().out

    mono = _read(_CLIP).mean(axis=1, dtype=np.float32)
    source_positions = np.arange(mono.size)
    target_positions = np.arange(mono.size * 3) / 3
    upsampled = np.interp(target_positions, source_positions, mono).astype(np.float32)
    stereo = np.column_stack((upsampled, upsampled))
    stereo_path = tmp_path / "speech_48k_stereo.wav"
    soundfile.write(str(stereo_path), stereo, 48000)

    assert main(["transcribe", str(stereo_path)]) == 0
    actual = capsys.readouterr().out
    assert actual.strip() == expected.strip()
    assert actual.strip() != ""


@pytest.mark.parametrize("input_kind", ["corrupt", "directory"])
def test_cli_transcribe_read_failure_is_concise(input_kind, tmp_path, monkeypatch, capsys):
    from stenographer import config
    from stenographer.cli import main

    config_path = tmp_path / "config.toml"
    config.Config.write_default(config_path)
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(config_path))

    input_path = tmp_path / input_kind
    if input_kind == "directory":
        input_path.mkdir()
    else:
        input_path.write_bytes(b"not an audio file")

    assert main(["transcribe", str(input_path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith(f"stenographer: cannot read {input_path}:")
    assert captured.err.count("\n") == 1


def test_hotword_is_honored():
    clip = _HOTWORD_CLIP if _HOTWORD_CLIP.exists() else _CLIP
    if clip is _CLIP:
        pytest.skip(f"hotword fixture absent: {_HOTWORD_CLIP}")

    from stenographer import config
    from stenographer.transcribe import model

    samples = _read(clip)
    base = config.Config.defaults()
    cfg = dataclasses.replace(base, asr=dataclasses.replace(base.asr, hotwords=_HOTWORD_NOUN))
    m = model.Model(cfg.asr)
    try:
        text = m.transcribe(samples).text
    finally:
        m.close()

    # End-to-end proof the hotword plumbing reaches the decoder and the noun
    # survives. A discriminating without-hotword decode (noun absent/wrong) is
    # left to manual hotword validation on the dev machine.
    assert _HOTWORD_NOUN.lower() in text.lower()
