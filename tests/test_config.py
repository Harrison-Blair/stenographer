# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for the config loader."""

from __future__ import annotations

import pathlib

import pytest

from stenographer.config import Config, ConfigError, default_toml, load_or_default


def test_config_error_message():
    # Interpolate the path rather than a POSIX literal: the rendered separator
    # is the host's, so "/x" would not match the WindowsPath spelling.
    path = pathlib.Path("/x")
    err = ConfigError(path, "asr.beam_size", "bad")
    assert str(err) == f"{path}: asr.beam_size: bad"
    assert err.key == "asr.beam_size"


def test_defaults_match_spec():
    d = Config.defaults()
    assert d.hotkey.binding == "KEY_RIGHTCTRL"
    assert d.hotkey.device is None
    assert d.hotkey.mode == "hold"
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
    assert d.feedback.update_check is True
    assert d.feedback.spectrum_floor_dbfs == -45.0
    assert d.feedback.sound_pack == "minimal-ui"


def test_write_default_round_trips(tmp_path):
    p = tmp_path / "config.toml"
    Config.write_default(p)
    assert Config.load(p) == Config.defaults()


def test_default_template_takes_its_hotkey_device_comment_from_the_platform():
    """``/dev/input/event*`` is a Linux fact, so the host supplies that comment.

    Seen to FAIL against the hardcoded template (the rendered comment stayed
    "explicit /dev/input/event* path" while the platform said otherwise).
    """

    from stenographer.platform import current_platform

    expected = current_platform().guidance().hotkey_device_comment
    rendered = default_toml()
    assert f'device = ""                    # {expected}\n' in rendered
    # The comment column is fixed so every annotated key still lines up.
    assert rendered.count("                    # ") == 1
    # Still valid, still the documented defaults.
    assert Config.loads(rendered) == Config.defaults()


def test_loads_validates_without_a_file():
    assert Config.loads("[stenographer.asr]\nbeam_size = 4\n").asr.beam_size == 4


def test_loads_uses_supplied_path_in_errors():
    path = pathlib.Path("reviewed-config.toml")
    with pytest.raises(ConfigError) as exc:
        Config.loads("[stenographer.asr]\nbeam_size = 0\n", path)
    assert exc.value.path == path


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
    assert cfg.feedback.spectrum_floor_dbfs == Config.defaults().feedback.spectrum_floor_dbfs
    assert cfg.feedback.sound_pack == "minimal-ui"


def test_update_check_can_be_disabled_without_restating_feedback_defaults(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[stenographer.feedback]\nupdate_check = false\n")
    cfg = Config.load(p)
    assert cfg.feedback.update_check is False
    assert cfg.feedback.overlay == Config.defaults().feedback.overlay
    assert cfg.feedback.volume == Config.defaults().feedback.volume


def test_config_written_before_update_check_existed_opts_in_without_migration(tmp_path):
    p = tmp_path / "config.toml"
    original = "[stenographer.feedback]\noverlay = false\n"
    p.write_text(original)

    assert Config.load(p).feedback.update_check is True
    assert p.read_text() == original


def test_default_template_documents_the_update_check_as_enabled():
    assert Config.loads(default_toml()).feedback.update_check is True


def test_old_config_inherits_default_sound_pack_without_migration(tmp_path):
    p = tmp_path / "config.toml"
    original = "[stenographer.feedback]\nvolume = 0.25\n"
    p.write_text(original)

    assert Config.load(p).feedback.sound_pack == "minimal-ui"
    assert p.read_text() == original


@pytest.mark.parametrize(
    "name",
    ["legacy", "warm-desk", "a", "a" * 64, "0-quiet"],
)
def test_sound_pack_accepts_slug_syntax_without_requiring_availability(tmp_path, name):
    p = tmp_path / "config.toml"
    p.write_text(f'[stenographer.feedback]\nsound_pack = "{name}"\n')

    assert Config.load(p).feedback.sound_pack == name


@pytest.mark.parametrize("floor", [-96, -45.5, -13])
def test_spectrum_floor_override_accepts_documented_range(tmp_path, floor):
    p = tmp_path / "config.toml"
    p.write_text(f"[stenographer.feedback]\nspectrum_floor_dbfs = {floor}\n")

    assert Config.load(p).feedback.spectrum_floor_dbfs == float(floor)


def test_spectrum_floor_accepts_exactly_eighteen_calibrated_bands(tmp_path):
    p = tmp_path / "config.toml"
    floors = [float(-80 + index) for index in range(18)]
    p.write_text(
        "[stenographer.feedback]\nspectrum_floor_dbfs = ["
        + ", ".join(str(value) for value in floors)
        + "]\n"
    )

    assert Config.load(p).feedback.spectrum_floor_dbfs == tuple(floors)


def test_toggle_mode_without_restating_hotkey_defaults(tmp_path):
    # Seen to FAIL against the pre-change loader (AttributeError: no mode field).
    p = tmp_path / "config.toml"
    p.write_text('[stenographer.hotkey]\nmode = "toggle"\n')
    cfg = Config.load(p)
    assert cfg.hotkey.mode == "toggle"
    assert cfg.hotkey.binding == Config.defaults().hotkey.binding
    assert cfg.hotkey.device == Config.defaults().hotkey.device


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
        ('[stenographer.feedback]\nupdate_check = "yes"\n', "feedback.update_check"),
        ('[stenographer.feedback]\nsound_pack = "Minimal UI"\n', "feedback.sound_pack"),
        ('[stenographer.feedback]\nsound_pack = "-minimal"\n', "feedback.sound_pack"),
        ('[stenographer.feedback]\nsound_pack = "a_thing"\n', "feedback.sound_pack"),
        (
            f'[stenographer.feedback]\nsound_pack = "{"a" * 65}"\n',
            "feedback.sound_pack",
        ),
        ("[stenographer.feedback]\nspectrum_floor_dbfs = -97\n", "feedback.spectrum_floor_dbfs"),
        ("[stenographer.feedback]\nspectrum_floor_dbfs = -12\n", "feedback.spectrum_floor_dbfs"),
        ('[stenographer.feedback]\nspectrum_floor_dbfs = "-45"\n', "feedback.spectrum_floor_dbfs"),
        (
            "[stenographer.feedback]\nspectrum_floor_dbfs = [-60, -50]\n",
            "feedback.spectrum_floor_dbfs",
        ),
        (
            "[stenographer.feedback]\nspectrum_floor_dbfs = ["
            + ", ".join(["-60"] * 17 + ["true"])
            + "]\n",
            "feedback.spectrum_floor_dbfs",
        ),
        ('[stenographer.hotkey]\nbinding = ""\n', "hotkey.binding"),
        ('[stenographer.hotkey]\nmode = "hybrid"\n', "hotkey.mode"),
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
