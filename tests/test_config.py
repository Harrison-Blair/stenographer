# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import pathlib
import textwrap
from dataclasses import FrozenInstanceError

import pytest

from stenographer.config import (
    CUE_NAMES,
    AsrConfig,
    AudioConfig,
    ClipboardConfig,
    Config,
    ConfigError,
    HotkeyConfig,
    OutputConfig,
    UpdateConfig,
    load_or_default,
    resolve_config_path,
)

# --- defaults() ---


def test_defaults_hotkey() -> None:
    assert Config.defaults().hotkey == HotkeyConfig(
        binding="KEY_RIGHTCTRL",
        toggle_threshold_seconds=0.5,
        device=None,
    )


def test_defaults_audio() -> None:
    assert Config.defaults().audio == AudioConfig(
        sample_rate=16000,
        frames_per_buffer=1024,
        input_device=None,
    )


def test_defaults_asr() -> None:
    assert Config.defaults().asr == AsrConfig(
        model="Systran/faster-whisper-large-v3",
        language="en",
        beam_size=5,
        compute_type="int8",
        silence_threshold=0.6,
        mode="lazy",
        idle_unload_seconds=3600,
    )


def test_defaults_feedback() -> None:
    fb = Config.defaults().feedback
    assert fb.volume == 0.6
    assert fb.mute is False
    assert set(fb.cues.keys()) == set(CUE_NAMES)
    assert all(v is None for v in fb.cues.values())


def test_defaults_output() -> None:
    assert Config.defaults().output == OutputConfig(
        injection_method="paste",
        append_trailing_space=True,
        max_chars=4096,
    )


def test_defaults_clipboard() -> None:
    assert Config.defaults().clipboard == ClipboardConfig(enabled=True)


def test_defaults_update() -> None:
    assert Config.defaults().update == UpdateConfig(
        repo="Harrison-Blair/stenographer",
        channel="stable",
        base_url="https://api.github.com",
        asset_pattern="stenographer-{version}-linux-x86_64.tar.gz",
        timeout_seconds=60,
    )


def test_defaults_is_frozen() -> None:
    cfg = Config.defaults()
    with pytest.raises(FrozenInstanceError):
        cfg.hotkey = None  # type: ignore[misc]


def test_defaults_returns_fresh_cues_dict() -> None:
    a = Config.defaults()
    b = Config.defaults()
    assert a.feedback.cues is not b.feedback.cues


# --- load(): overrides ---


def test_load_full_override(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text(
        textwrap.dedent("""\
            [stenographer]
            hotkey.binding = "KEY_F12"
            hotkey.toggle_threshold_seconds = 1.5
            audio.sample_rate = 48000
            audio.frames_per_buffer = 2048
            asr.model = "Systran/faster-whisper-tiny.en"
            asr.language = "en"
            asr.beam_size = 3
            asr.compute_type = "int8"
            feedback.volume = 0.3
            feedback.mute = true
            output.injection_method = "paste"
            output.append_trailing_space = false
            output.max_chars = 1000
            clipboard.enabled = false
            """)
    )
    cfg = Config.load(p)
    assert cfg.hotkey.binding == "KEY_F12"
    assert cfg.hotkey.toggle_threshold_seconds == 1.5
    assert cfg.audio.sample_rate == 48000
    assert cfg.audio.frames_per_buffer == 2048
    assert cfg.asr.model == "Systran/faster-whisper-tiny.en"
    assert cfg.asr.beam_size == 3
    assert cfg.asr.compute_type == "int8"
    assert cfg.feedback.volume == 0.3
    assert cfg.feedback.mute is True
    assert cfg.output.injection_method == "paste"
    assert cfg.output.append_trailing_space is False
    assert cfg.output.max_chars == 1000
    assert cfg.clipboard.enabled is False


def test_load_partial_override_merges_over_defaults(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text(
        textwrap.dedent("""\
            [stenographer]
            hotkey.binding = "KEY_F1"
            audio.sample_rate = 48000
            """)
    )
    cfg = Config.load(p)
    assert cfg.hotkey.binding == "KEY_F1"
    assert cfg.hotkey.toggle_threshold_seconds == 0.5
    assert cfg.hotkey.device is None
    assert cfg.audio.sample_rate == 48000
    assert cfg.audio.frames_per_buffer == 1024
    assert cfg.audio.input_device is None
    assert cfg.asr.beam_size == 5
    assert cfg.feedback.volume == 0.6
    assert cfg.output.injection_method == "paste"
    assert cfg.output.max_chars == 4096
    assert cfg.clipboard.enabled is True


def test_load_empty_file_yields_defaults(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("")
    assert Config.load(p) == Config.defaults()


def test_load_no_stenographer_table_yields_defaults(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("# empty config file\n")
    assert Config.load(p) == Config.defaults()


def test_load_cues_partial_override(tmp_path: pathlib.Path) -> None:
    cue = tmp_path / "cue.wav"
    cue.write_text("data")
    p = tmp_path / "config.toml"
    p.write_text(
        textwrap.dedent("""\
            [stenographer.feedback.cues]
            ptt_on = "%s"
            """)
        % cue
    )
    cfg = Config.load(p)
    assert cfg.feedback.cues["ptt_on"] == str(cue)
    assert cfg.feedback.cues["ptt_off"] is None
    assert cfg.feedback.cues["transcribe_done"] is None


# --- load(): malformed / missing ---


def test_load_malformed_toml_raises(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('hotkey.binding = "unclosed string\n')
    with pytest.raises(ConfigError, match="malformed"):
        Config.load(p)


def test_load_missing_file_raises(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "nope.toml"
    with pytest.raises(ConfigError, match="cannot read"):
        Config.load(p)


# --- load(): validation rules ---


def test_validate_hotkey_threshold_zero_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("[stenographer]\nhotkey.toggle_threshold_seconds = 0\n")
    with pytest.raises(ConfigError, match=r"hotkey.toggle_threshold_seconds"):
        Config.load(p)


def test_validate_hotkey_threshold_negative_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("[stenographer]\nhotkey.toggle_threshold_seconds = -0.5\n")
    with pytest.raises(ConfigError, match=r"hotkey.toggle_threshold_seconds"):
        Config.load(p)


def test_validate_hotkey_threshold_too_high_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("[stenographer]\nhotkey.toggle_threshold_seconds = 5.5\n")
    with pytest.raises(ConfigError, match=r"hotkey.toggle_threshold_seconds"):
        Config.load(p)


def test_validate_hotkey_threshold_upper_bound_accepted(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("[stenographer]\nhotkey.toggle_threshold_seconds = 5\n")
    assert Config.load(p).hotkey.toggle_threshold_seconds == 5.0


def test_validate_hotkey_binding_empty_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('[stenographer]\nhotkey.binding = ""\n')
    with pytest.raises(ConfigError, match=r"hotkey.binding"):
        Config.load(p)


def test_validate_sample_rate_invalid_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("[stenographer]\naudio.sample_rate = 12345\n")
    with pytest.raises(ConfigError, match=r"audio.sample_rate"):
        Config.load(p)


def test_validate_sample_rate_float_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("[stenographer]\naudio.sample_rate = 16000.0\n")
    with pytest.raises(ConfigError, match=r"audio.sample_rate"):
        Config.load(p)


def test_validate_frames_per_buffer_too_low_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("[stenographer]\naudio.frames_per_buffer = 32\n")
    with pytest.raises(ConfigError, match=r"audio.frames_per_buffer"):
        Config.load(p)


def test_validate_frames_per_buffer_too_high_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("[stenographer]\naudio.frames_per_buffer = 16384\n")
    with pytest.raises(ConfigError, match=r"audio.frames_per_buffer"):
        Config.load(p)


def test_validate_beam_size_too_low_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("[stenographer]\nasr.beam_size = 0\n")
    with pytest.raises(ConfigError, match=r"asr.beam_size"):
        Config.load(p)


def test_validate_beam_size_too_high_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("[stenographer]\nasr.beam_size = 11\n")
    with pytest.raises(ConfigError, match=r"asr.beam_size"):
        Config.load(p)


def test_validate_compute_type_invalid_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('[stenographer]\nasr.compute_type = "bogus"\n')
    with pytest.raises(ConfigError, match=r"asr.compute_type"):
        Config.load(p)


def test_validate_asr_mode_eager_accepted(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('[stenographer]\nasr.mode = "eager"\n')
    assert Config.load(p).asr.mode == "eager"


def test_validate_asr_mode_lazy_accepted(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('[stenographer]\nasr.mode = "lazy"\n')
    assert Config.load(p).asr.mode == "lazy"


def test_validate_asr_mode_invalid_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('[stenographer]\nasr.mode = "fast"\n')
    with pytest.raises(ConfigError, match=r"asr.mode"):
        Config.load(p)


def test_validate_idle_unload_seconds_negative_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("[stenographer]\nasr.idle_unload_seconds = -1\n")
    with pytest.raises(ConfigError, match=r"asr.idle_unload_seconds"):
        Config.load(p)


def test_validate_idle_unload_seconds_too_high_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("[stenographer]\nasr.idle_unload_seconds = 100000\n")
    with pytest.raises(ConfigError, match=r"asr.idle_unload_seconds"):
        Config.load(p)


def test_validate_idle_unload_seconds_zero_accepted(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("[stenographer]\nasr.idle_unload_seconds = 0\n")
    assert Config.load(p).asr.idle_unload_seconds == 0


def test_validate_idle_unload_seconds_upper_bound_accepted(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("[stenographer]\nasr.idle_unload_seconds = 86400\n")
    assert Config.load(p).asr.idle_unload_seconds == 86400


def test_write_default_includes_asr_mode(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    Config.write_default(p)
    text = p.read_text(encoding="utf-8")
    assert 'asr.mode = "lazy"' in text
    assert "asr.idle_unload_seconds = 3600" in text


def test_validate_volume_negative_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("[stenographer]\nfeedback.volume = -0.1\n")
    with pytest.raises(ConfigError, match=r"feedback.volume"):
        Config.load(p)


def test_validate_volume_too_high_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("[stenographer]\nfeedback.volume = 1.5\n")
    with pytest.raises(ConfigError, match=r"feedback.volume"):
        Config.load(p)


def test_validate_max_chars_too_low_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("[stenographer]\noutput.max_chars = 0\n")
    with pytest.raises(ConfigError, match=r"output.max_chars"):
        Config.load(p)


def test_validate_max_chars_too_high_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("[stenographer]\noutput.max_chars = 200000\n")
    with pytest.raises(ConfigError, match=r"output.max_chars"):
        Config.load(p)


def test_validate_update_repo_missing_slash_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('[stenographer]\nupdate.repo = "no-slash"\n')
    with pytest.raises(ConfigError, match=r"update.repo"):
        Config.load(p)


def test_validate_update_channel_invalid_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('[stenographer]\nupdate.channel = "daily"\n')
    with pytest.raises(ConfigError, match=r"update.channel"):
        Config.load(p)


def test_validate_update_base_url_non_http_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('[stenographer]\nupdate.base_url = "ftp://example.com"\n')
    with pytest.raises(ConfigError, match=r"update.base_url"):
        Config.load(p)


def test_validate_update_base_url_trailing_slash_stripped(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('[stenographer]\nupdate.base_url = "https://api.github.com/"\n')
    assert Config.load(p).update.base_url == "https://api.github.com"


def test_validate_update_asset_pattern_missing_placeholder_rejected(
    tmp_path: pathlib.Path,
) -> None:
    p = tmp_path / "config.toml"
    p.write_text('[stenographer]\nupdate.asset_pattern = "stenographer.tar.gz"\n')
    with pytest.raises(ConfigError, match=r"update.asset_pattern"):
        Config.load(p)


def test_validate_update_timeout_too_low_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("[stenographer]\nupdate.timeout_seconds = 0\n")
    with pytest.raises(ConfigError, match=r"update.timeout_seconds"):
        Config.load(p)


def test_validate_update_timeout_too_high_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("[stenographer]\nupdate.timeout_seconds = 1000\n")
    with pytest.raises(ConfigError, match=r"update.timeout_seconds"):
        Config.load(p)


def test_validate_injection_method_invalid_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('[stenographer]\noutput.injection_method = "bogus"\n')
    with pytest.raises(ConfigError, match=r"output.injection_method"):
        Config.load(p)


def test_validate_injection_method_text_accepted(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('[stenographer]\noutput.injection_method = "text"\n')
    assert Config.load(p).output.injection_method == "text"


def test_validate_injection_method_paste_accepted(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('[stenographer]\noutput.injection_method = "paste"\n')
    assert Config.load(p).output.injection_method == "paste"


def test_validate_cue_unreadable_file_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('[stenographer.feedback.cues]\nptt_on = "/no/such/file.wav"\n')
    with pytest.raises(ConfigError, match=r"feedback.cues.ptt_on"):
        Config.load(p)


def test_validate_cue_readable_file_accepted(tmp_path: pathlib.Path) -> None:
    cue = tmp_path / "cue.wav"
    cue.write_text("data")
    p = tmp_path / "config.toml"
    p.write_text(f'[stenographer.feedback.cues]\nptt_on = "{cue}"\n')
    assert Config.load(p).feedback.cues["ptt_on"] == str(cue)


def test_validate_hotkey_device_missing_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('[stenographer]\nhotkey.device = "/no/such/device"\n')
    with pytest.raises(ConfigError, match=r"hotkey.device"):
        Config.load(p)


def test_validate_hotkey_device_existing_accepted(tmp_path: pathlib.Path) -> None:
    dev = tmp_path / "device"
    dev.write_text("")
    p = tmp_path / "config.toml"
    p.write_text(f'[stenographer]\nhotkey.device = "{dev}"\n')
    assert Config.load(p).hotkey.device == str(dev)


def test_validate_null_treated_as_empty_string(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text(
        textwrap.dedent("""\
            [stenographer]
            hotkey.device = null
            audio.input_device = null

            [stenographer.feedback.cues]
            ptt_on = null
            """)
    )
    cfg = Config.load(p)
    assert cfg.hotkey.device is None
    assert cfg.audio.input_device is None
    assert cfg.feedback.cues["ptt_on"] is None


def test_validate_wrong_type_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('[stenographer]\naudio.sample_rate = "not an int"\n')
    with pytest.raises(ConfigError, match=r"audio.sample_rate"):
        Config.load(p)


def test_validate_bool_rejected_for_int_field(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("[stenographer]\naudio.sample_rate = true\n")
    with pytest.raises(ConfigError, match=r"audio.sample_rate"):
        Config.load(p)


# --- write_default() round-trip ---


def test_write_default_round_trip(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    Config.write_default(p)
    assert p.is_file()
    assert Config.load(p) == Config.defaults()


def test_write_default_is_valid_toml(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    Config.write_default(p)
    text = p.read_text(encoding="utf-8")
    assert "[stenographer]" in text
    assert "[stenographer.feedback.cues]" in text
    assert "hotkey.binding" in text
    assert "asr.compute_type" in text


# --- resolve_config_path() ---


def test_resolve_config_path_stenographer_env_wins(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_path = tmp_path / "custom.toml"
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(env_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert resolve_config_path() == env_path
    assert env_path.parent.is_dir()


def test_resolve_config_path_xdg(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STENOGRAPHER_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    result = resolve_config_path()
    assert result == tmp_path / "stenographer" / "config.toml"
    assert result.parent.is_dir()


def test_resolve_config_path_home_default(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("STENOGRAPHER_CONFIG", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    result = resolve_config_path()
    assert result == tmp_path / ".config" / "stenographer" / "config.toml"
    assert result.parent.is_dir()


def test_resolve_config_path_creates_nested_dirs(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("STENOGRAPHER_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "deep" / "xdg"))
    result = resolve_config_path()
    assert result.parent.is_dir()


# --- load_or_default() ---


def test_load_or_default_writes_file_when_missing(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.toml"
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(config_path))
    assert not config_path.exists()
    cfg = load_or_default()
    assert config_path.is_file()
    assert cfg == Config.defaults()


def test_load_or_default_loads_existing(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('[stenographer]\nhotkey.binding = "KEY_F5"\n')
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(config_path))
    cfg = load_or_default()
    assert cfg.hotkey.binding == "KEY_F5"
    # untouched keys still take defaults
    assert cfg.hotkey.toggle_threshold_seconds == 0.5


def test_load_or_default_uses_xdg_when_env_unset(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("STENOGRAPHER_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg = load_or_default()
    expected = tmp_path / "stenographer" / "config.toml"
    assert expected.is_file()
    assert cfg == Config.defaults()
