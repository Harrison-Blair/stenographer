# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for the reauthored config loader."""

from __future__ import annotations

import pathlib

import pytest

from stenographer.config import Config, ConfigError, load_or_default


def test_config_error_message():
    err = ConfigError(pathlib.Path("/x"), "asr.beam_size", "bad")
    assert str(err) == "/x: asr.beam_size: bad"
    assert err.key == "asr.beam_size"


def test_defaults_match_spec():
    d = Config.defaults()
    assert d.hotkey.binding == "KEY_RIGHTCTRL"
    assert d.hotkey.device is None
    assert d.audio.input_device is None
    assert d.audio.min_speech_rms == 0.0005
    assert d.audio.max_recording_seconds == 600
    assert d.asr.model == "Systran/faster-whisper-medium.en"
    assert d.asr.compute_type == "int8"
    assert d.asr.beam_size == 1
    assert d.asr.hotwords is None
    assert d.asr.initial_prompt is None
    assert d.asr.vad_filter is True
    assert d.asr.silence_threshold == 0.6
    assert d.asr.idle_unload_seconds == 900
    assert d.asr.cpu_threads == 0
    assert d.feedback.volume == 0.6
    assert d.feedback.mute is False
    assert d.feedback.overlay is True


def test_write_default_round_trips(tmp_path):
    p = tmp_path / "config.toml"
    Config.write_default(p)
    assert Config.load(p) == Config.defaults()


def test_load_or_default_writes_missing_file(tmp_path, monkeypatch):
    p = tmp_path / "nested" / "config.toml"
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(p))
    cfg = load_or_default()
    assert p.is_file()
    assert cfg == Config.defaults()


def test_partial_override_leaves_other_keys(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[stenographer.asr]\nbeam_size = 5\n")
    cfg = Config.load(p)
    assert cfg.asr.beam_size == 5
    assert cfg.asr.model == Config.defaults().asr.model
    assert cfg.hotkey == Config.defaults().hotkey
    assert cfg.feedback == Config.defaults().feedback


def test_overlay_can_be_disabled_without_restating_feedback_defaults(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[stenographer.feedback]\noverlay = false\n")
    cfg = Config.load(p)
    assert cfg.feedback.overlay is False
    assert cfg.feedback.volume == Config.defaults().feedback.volume
    assert cfg.feedback.mute == Config.defaults().feedback.mute


def test_empty_string_is_unset(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[stenographer.hotkey]\ndevice = ""\n'
        '[stenographer.audio]\ninput_device = ""\n'
        '[stenographer.asr]\nhotwords = ""\ninitial_prompt = ""\n'
    )
    cfg = Config.load(p)
    assert cfg.hotkey.device is None
    assert cfg.audio.input_device is None
    assert cfg.asr.hotwords is None
    assert cfg.asr.initial_prompt is None


def test_unknown_keys_ignored(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[stenographer.asr]\nbogus = 42\n")
    assert Config.load(p) == Config.defaults()


@pytest.mark.parametrize(
    ("toml_text", "key"),
    [
        ('[stenographer.asr]\ncompute_type = "int4"\n', "asr.compute_type"),
        ("[stenographer.asr]\nbeam_size = 0\n", "asr.beam_size"),
        ('[stenographer.asr]\nbeam_size = "x"\n', "asr.beam_size"),
        ("[stenographer.asr]\nsilence_threshold = 2\n", "asr.silence_threshold"),
        ("[stenographer.asr]\ncpu_threads = 100\n", "asr.cpu_threads"),
        ("[stenographer.feedback]\nvolume = -1\n", "feedback.volume"),
        ('[stenographer.feedback]\nmute = "no"\n', "feedback.mute"),
        ('[stenographer.feedback]\noverlay = "yes"\n', "feedback.overlay"),
        ('[stenographer.hotkey]\nbinding = ""\n', "hotkey.binding"),
        ("[stenographer.audio]\nmax_recording_seconds = 0\n", "audio.max_recording_seconds"),
    ],
)
def test_out_of_range_or_wrong_type_raises(tmp_path, toml_text, key):
    p = tmp_path / "config.toml"
    p.write_text(toml_text)
    with pytest.raises(ConfigError) as exc:
        Config.load(p)
    assert exc.value.key == key


@pytest.mark.parametrize(
    ("toml_text", "key"),
    [
        ('[stenographer]\nasr = "medium"\n', "asr"),
        ("[stenographer]\nhotkey = 1\n", "hotkey"),
        ("[stenographer]\naudio = true\n", "audio"),
        ('[stenographer]\nfeedback = "x"\n', "feedback"),
    ],
)
def test_scalar_section_raises_config_error(tmp_path, toml_text, key):
    p = tmp_path / "config.toml"
    p.write_text(toml_text)
    with pytest.raises(ConfigError) as exc:
        Config.load(p)
    assert exc.value.key == key


def test_malformed_toml_raises(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("this is = = not valid")
    with pytest.raises(ConfigError) as exc:
        Config.load(p)
    assert exc.value.key == "<toml>"
