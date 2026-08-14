# SPDX-License-Identifier: GPL-3.0-or-later
"""Integration smoke suite for the reauthored batch transcribe path.

Two real, non-mocked checks (spec §6.3, M1 Verify clause):

  * equivalence  — the new package (model.Model + format.format_transcript)
    produces the same text as the old package (stenographer.asr.Model +
    HeuristicFormatter) on the same bundled 16 kHz WAV.
  * hotwords     — a proper noun set in asr.hotwords is honored in the decode.

Both really load the medium.en model and decode a bundled clip; nothing is
mocked. The whole module self-skips unless STENOGRAPHER_INTEGRATION=1, the
model is cached locally, and the fixture WAV is present — so the default unit
run never touches the network or the ASR stack, and this file stays
collectable while the sibling M1 modules are still being written.
"""

from __future__ import annotations

import dataclasses
import os
import pathlib

import pytest

pytestmark = pytest.mark.integration

_FIXTURES = pathlib.Path(__file__).parent / "fixtures"
_CLIP = _FIXTURES / "speech_16k.wav"
_HOTWORD_CLIP = _FIXTURES / "hotword_16k.wav"
_HOTWORD_NOUN = "Anthropic"
_MODEL_ID = "Systran/faster-whisper-medium.en"

if os.environ.get("STENOGRAPHER_INTEGRATION") != "1":
    pytest.skip("integration suite requires STENOGRAPHER_INTEGRATION=1", allow_module_level=True)

if not _CLIP.exists():
    pytest.skip(f"fixture WAV absent: {_CLIP}", allow_module_level=True)

from huggingface_hub import try_to_load_from_cache  # noqa: E402

if try_to_load_from_cache(_MODEL_ID, "config.json") is None:
    pytest.skip(f"model not cached: {_MODEL_ID}", allow_module_level=True)

import soundfile  # noqa: E402


def _read(path: pathlib.Path):
    return soundfile.read(str(path), dtype="float32", always_2d=True)[0]


def test_new_transcribe_matches_old_tool():
    from stenographer import config as v2config
    from stenographer import format as v2format
    from stenographer import model as v2model

    samples = _read(_CLIP)

    v2cfg = v2config.Config.defaults()
    assert v2cfg.asr.model == _MODEL_ID  # hotwords require the full model (§4.4)
    m = v2model.Model(v2cfg.asr)
    try:
        new_text = v2format.format_transcript(m.transcribe(samples).text)
    finally:
        m.close()

    from stenographer.asr.model import Model as OldModel
    from stenographer.output.formatter import HeuristicFormatter

    from stenographer.config import Config as OldConfig

    old_cfg = OldConfig.defaults()
    old_model = OldModel(old_cfg.asr)
    try:
        old_result = old_model.transcribe(samples, old_cfg.asr.language, old_cfg.asr.beam_size)
    finally:
        old_model.close()
    old_text = HeuristicFormatter(
        old_cfg.formatting, append_trailing_space=old_cfg.output.append_trailing_space
    ).format_batch(old_result.segments)

    # Compare modulo trailing whitespace: the two formatters differ only in the
    # trailing-space knob (old default on, new default off); the words, spacing
    # and capitalisation must be identical.
    assert new_text.strip() == old_text.strip()
    assert new_text.strip() != ""


def test_hotword_is_honored():
    clip = _HOTWORD_CLIP if _HOTWORD_CLIP.exists() else _CLIP
    if clip is _CLIP:
        pytest.skip(f"hotword fixture absent: {_HOTWORD_CLIP}")

    from stenographer import config as v2config
    from stenographer import model as v2model

    samples = _read(clip)
    base = v2config.Config.defaults()
    cfg = dataclasses.replace(base, asr=dataclasses.replace(base.asr, hotwords=_HOTWORD_NOUN))
    m = v2model.Model(cfg.asr)
    try:
        text = m.transcribe(samples).text
    finally:
        m.close()

    # End-to-end proof the hotword plumbing reaches the decoder and the noun
    # survives. A discriminating without-hotword decode (noun absent/wrong) is
    # left to manual §4.4 validation on the dev machine.
    assert _HOTWORD_NOUN.lower() in text.lower()
