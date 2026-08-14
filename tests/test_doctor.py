# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for the doctor report: decision and rendering only.

The environment probe itself is exercised by test_doctor_smoke.py (integration,
non-mocked) per spec §6 — nothing here stubs the environment.
"""

from __future__ import annotations

import pathlib

from stenographer import doctor
from stenographer.config import Config


def _caps(**overrides) -> doctor.Capabilities:
    fields = {
        "uinput_writable": True,
        "input_group": True,
        "has_mic": True,
        "model_cached": True,
        "wl_copy": True,
        "audio_player": "pw-play",
    }
    fields.update(overrides)
    return doctor.Capabilities(**fields)


def test_missing_required_empty_when_all_present():
    assert doctor.missing_required(_caps()) == []


def test_missing_required_names_each_absent_capability():
    caps = _caps(uinput_writable=False, model_cached=False)
    assert doctor.missing_required(caps) == ["uinput_writable", "model_cached"]


def test_audio_player_is_not_required():
    assert doctor.missing_required(_caps(audio_player=None)) == []


def test_render_all_present():
    report = doctor.render(_caps(), Config.defaults(), pathlib.Path("/tmp/config.toml"))
    assert "all required capabilities present" in report
    assert "MISSING" not in report
    assert "/tmp/config.toml" in report
    assert "audio player: pw-play" in report


def test_render_missing_capability_carries_fix_hint():
    caps = _caps(model_cached=False, wl_copy=False)
    report = doctor.render(caps, Config.defaults(), pathlib.Path("/tmp/config.toml"))
    assert "ASR model cached: MISSING — run: stenographer model download" in report
    assert "wl-copy: MISSING — install wl-clipboard" in report
    assert "missing required capabilities: model_cached, wl_copy" in report


def test_render_absent_audio_player_is_informational():
    report = doctor.render(_caps(audio_player=None), Config.defaults(), pathlib.Path("/x"))
    assert "audio player: none (sound cues disabled)" in report
    assert "all required capabilities present" in report
