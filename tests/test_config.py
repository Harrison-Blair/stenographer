# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import pathlib
import re
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
    VisualizerConfig,
    load_or_default,
    resolve_config_path,
)

# --- defaults() ---


def test_defaults_hotkey() -> None:
    assert Config.defaults().hotkey == HotkeyConfig(
        binding="KEY_RIGHTALT",
        toggle_threshold_seconds=0.5,
        double_tap_window_seconds=0.35,
        cancel_binding="KEY_ESC",
        device=None,
        trigger_mode="ptt",
    )


def test_defaults_have_no_prompt_binding_field() -> None:
    assert not hasattr(Config.defaults().hotkey, "prompt_binding")


def test_defaults_have_no_llm_field() -> None:
    assert not hasattr(Config.defaults(), "llm")


def test_default_hotkey_binding_is_right_alt() -> None:
    assert Config.defaults().hotkey.binding == "KEY_RIGHTALT"


def test_legacy_llm_and_prompt_binding_keys_ignored(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text(
        textwrap.dedent("""\
            [stenographer]
            hotkey.prompt_binding = "KEY_RIGHTALT"

            [stenographer.llm]
            base_url = "http://localhost:9090"
            model = "qwen2.5-7b"
            """)
    )
    Config.load(p)  # must not raise


def test_format_default_toml_has_no_llm_or_prompt_binding() -> None:
    from stenographer.config import _format_default_toml

    text = _format_default_toml()
    assert "llm." not in text
    assert "prompt_binding" not in text
    assert 'hotkey.binding = "KEY_RIGHTALT"' in text


def test_defaults_audio() -> None:
    assert Config.defaults().audio == AudioConfig(
        sample_rate=16000,
        frames_per_buffer=1024,
        input_device=None,
        max_recording_seconds=600,
        silence_detection=True,
        silence_rms_threshold=0.01,
        silence_duration_seconds=1.5,
    )


def test_defaults_asr() -> None:
    assert Config.defaults().asr == AsrConfig(
        model="Systran/faster-whisper-medium.en",
        language="en",
        beam_size=5,
        compute_type="int8",
        silence_threshold=0.6,
        mode="lazy",
        idle_unload_seconds=300,
        hotwords=None,
        initial_prompt=None,
    )


def test_defaults_feedback() -> None:
    fb = Config.defaults().feedback
    assert fb.volume == 0.6
    assert fb.mute is False
    assert set(fb.cues.keys()) == set(CUE_NAMES)
    assert all(v is None for v in fb.cues.values())


def test_defaults_visualizer() -> None:
    assert Config.defaults().visualizer == VisualizerConfig(
        enabled=True,
        frequency_bands=16,
        min_frequency=80.0,
        max_frequency=8000.0,
        margin_bottom=32,
    )


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
            visualizer.frequency_bands = 20
            visualizer.margin_bottom = 48
            output.injection_method = "text"
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
    assert cfg.visualizer.frequency_bands == 20
    assert cfg.visualizer.margin_bottom == 48
    # text mode, so clipboard.enabled = false is coherent here; paste mode
    # delivers *via* the clipboard and is covered by the cross-section tests.
    assert cfg.output.injection_method == "text"
    assert cfg.output.append_trailing_space is False
    assert cfg.output.max_chars == 1000
    assert cfg.clipboard.enabled is False


def test_paste_mode_requires_clipboard_enabled(tmp_path: pathlib.Path) -> None:
    # Paste mode delivers text by copying it and firing Shift+Insert. With the
    # clipboard disabled the chord would paste whatever the user had there
    # before, so the combination is rejected rather than silently resolved.
    p = tmp_path / "config.toml"
    p.write_text(
        textwrap.dedent("""\
            [stenographer]
            output.injection_method = "paste"
            clipboard.enabled = false
            """)
    )
    with pytest.raises(ConfigError, match=re.escape("clipboard.enabled")):
        Config.load(p)


def test_streaming_requires_paste_mode(tmp_path: pathlib.Path) -> None:
    # Streaming pastes each committed delta; in text mode it silently did
    # nothing at all, which read as the feature being broken.
    p = tmp_path / "config.toml"
    p.write_text(
        textwrap.dedent("""\
            [stenographer]
            output.injection_method = "text"
            streaming.enabled = true
            """)
    )
    with pytest.raises(ConfigError, match=re.escape("streaming.enabled")):
        Config.load(p)


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


def test_hotkey_trigger_mode_toggle_parses(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('[stenographer]\nhotkey.trigger_mode = "toggle"\n')
    assert Config.load(p).hotkey.trigger_mode == "toggle"


def test_hotkey_trigger_mode_invalid_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('[stenographer]\nhotkey.trigger_mode = "bogus"\n')
    with pytest.raises(ConfigError, match=r"hotkey.trigger_mode"):
        Config.load(p)


def test_trigger_mode_accepts_ptt(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('[stenographer]\nhotkey.trigger_mode = "ptt"\n')
    assert Config.load(p).hotkey.trigger_mode == "ptt"
    # ...and an unknown value still raises the existing ConfigError shape.
    q = tmp_path / "bad.toml"
    q.write_text('[stenographer]\nhotkey.trigger_mode = "nonsense"\n')
    with pytest.raises(ConfigError, match=r"hotkey.trigger_mode"):
        Config.load(q)


def test_defaults_trigger_mode_is_ptt() -> None:
    assert Config.defaults().hotkey.trigger_mode == "ptt"


def test_format_default_toml_has_trigger_mode() -> None:
    from stenographer.config import _format_default_toml

    assert 'hotkey.trigger_mode = "ptt"' in _format_default_toml()


def test_asr_hotwords_and_initial_prompt_override(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text(
        textwrap.dedent("""\
            [stenographer]
            asr.hotwords = "stenographer, wtype, Wayland"
            asr.initial_prompt = "Notes about Arch Linux tooling."
            """)
    )
    cfg = Config.load(p)
    assert cfg.asr.hotwords == "stenographer, wtype, Wayland"
    assert cfg.asr.initial_prompt == "Notes about Arch Linux tooling."


def test_asr_hotwords_empty_string_is_none(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text(
        textwrap.dedent("""\
            [stenographer]
            asr.hotwords = ""
            asr.initial_prompt = null
            """)
    )
    cfg = Config.load(p)
    assert cfg.asr.hotwords is None
    assert cfg.asr.initial_prompt is None


def test_asr_hotwords_non_string_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("[stenographer]\nasr.hotwords = 42\n")
    with pytest.raises(ConfigError, match=r"asr.hotwords"):
        Config.load(p)


def test_format_default_toml_has_vocabulary_keys() -> None:
    from stenographer.config import _format_default_toml

    toml = _format_default_toml()
    assert 'asr.hotwords = ""' in toml
    assert 'asr.initial_prompt = ""' in toml


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


def test_validate_double_tap_window_out_of_range_rejected(tmp_path: pathlib.Path) -> None:
    for bad in ("0", "-0.1", "2.5"):
        p = tmp_path / "config.toml"
        p.write_text(f"[stenographer]\nhotkey.double_tap_window_seconds = {bad}\n")
        with pytest.raises(ConfigError, match=r"hotkey.double_tap_window_seconds"):
            Config.load(p)


def test_validate_double_tap_window_accepted(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("[stenographer]\nhotkey.double_tap_window_seconds = 0.5\n")
    assert Config.load(p).hotkey.double_tap_window_seconds == 0.5


def test_validate_cancel_binding_unknown_key_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('[stenographer]\nhotkey.cancel_binding = "NOT_A_KEY"\n')
    with pytest.raises(ConfigError, match=r"hotkey.cancel_binding"):
        Config.load(p)


def test_validate_cancel_binding_overlap_with_main_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('[stenographer]\nhotkey.cancel_binding = "KEY_RIGHTALT"\n')
    with pytest.raises(ConfigError, match=r"hotkey.cancel_binding"):
        Config.load(p)


def test_validate_cancel_binding_empty_disables(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('[stenographer]\nhotkey.cancel_binding = ""\n')
    assert Config.load(p).hotkey.cancel_binding == ""


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


def test_validate_silence_detection_non_bool_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("[stenographer]\naudio.silence_detection = 1\n")
    with pytest.raises(ConfigError, match=r"audio.silence_detection"):
        Config.load(p)


def test_validate_silence_rms_threshold_too_high_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("[stenographer]\naudio.silence_rms_threshold = 1.5\n")
    with pytest.raises(ConfigError, match=r"audio.silence_rms_threshold"):
        Config.load(p)


def test_validate_silence_duration_zero_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("[stenographer]\naudio.silence_duration_seconds = 0\n")
    with pytest.raises(ConfigError, match=r"audio.silence_duration_seconds"):
        Config.load(p)


def test_validate_silence_duration_too_high_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("[stenographer]\naudio.silence_duration_seconds = 11\n")
    with pytest.raises(ConfigError, match=r"audio.silence_duration_seconds"):
        Config.load(p)


def test_load_silence_override_round_trips(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text(
        "[stenographer]\n"
        "audio.silence_detection = false\n"
        "audio.silence_rms_threshold = 0.05\n"
        "audio.silence_duration_seconds = 2.5\n"
    )
    cfg = Config.load(p)
    assert cfg.audio.silence_detection is False
    assert cfg.audio.silence_rms_threshold == 0.05
    assert cfg.audio.silence_duration_seconds == 2.5


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
    assert "asr.idle_unload_seconds = 300" in text


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


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("frequency_bands", "5"),
        ("frequency_bands", "33"),
        ("min_frequency", "10"),
        ("max_frequency", "25000"),
        ("margin_bottom", "-1"),
        ("margin_bottom", "501"),
    ],
)
def test_validate_visualizer_ranges_rejected(
    tmp_path: pathlib.Path,
    key: str,
    value: str,
) -> None:
    p = tmp_path / "config.toml"
    p.write_text(f"[stenographer]\nvisualizer.{key} = {value}\n")
    with pytest.raises(ConfigError, match=rf"visualizer\.{key}"):
        Config.load(p)


def test_validate_visualizer_frequency_order_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text(
        "[stenographer]\nvisualizer.min_frequency = 1500\nvisualizer.max_frequency = 1200\n"
    )
    with pytest.raises(ConfigError, match=r"visualizer.max_frequency"):
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


def test_unknown_cue_name_still_rejected(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('[stenographer.feedback.cues]\nbogus_cue_name = "/no/such/file.wav"\n')
    with pytest.raises(ConfigError, match=r"feedback.cues.bogus_cue_name"):
        Config.load(p)


def test_cue_names_matches_cue_name_literal_args() -> None:
    import typing

    from stenographer.audio.feedback import CueName

    assert set(CUE_NAMES) == set(typing.get_args(CueName))


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


# --- [streaming] / [formatting] ---


def test_streaming_defaults() -> None:
    cfg = Config.defaults()
    assert cfg.streaming.enabled is False
    assert cfg.streaming.min_chunk_seconds == 1.0
    assert cfg.streaming.agreement_n == 2
    assert cfg.streaming.beam_size is None
    assert cfg.streaming.max_buffer_seconds == 20.0
    assert cfg.formatting.capitalize_sentences is True
    assert cfg.formatting.normalize_spacing is True


def test_default_paragraph_pause_seconds_is_zero() -> None:
    assert Config.defaults().formatting.paragraph_pause_seconds == 0.0


def test_streaming_overrides_load(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text(
        "[stenographer]\n"
        "streaming.enabled = true\n"
        "streaming.min_chunk_seconds = 0.5\n"
        "streaming.agreement_n = 3\n"
        "streaming.beam_size = 2\n"
        "streaming.max_buffer_seconds = 30\n"
        "formatting.paragraph_pause_seconds = 3.5\n"
        "formatting.capitalize_sentences = false\n"
    )
    cfg = Config.load(p)
    assert cfg.streaming.enabled is True
    assert cfg.streaming.min_chunk_seconds == 0.5
    assert cfg.streaming.agreement_n == 3
    assert cfg.streaming.beam_size == 2
    assert cfg.streaming.max_buffer_seconds == 30.0
    assert cfg.formatting.paragraph_pause_seconds == 3.5
    assert cfg.formatting.capitalize_sentences is False


def test_streaming_beam_size_null_means_asr_beam(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("[stenographer]\nstreaming.beam_size = null\n")
    assert Config.load(p).streaming.beam_size is None


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("streaming.min_chunk_seconds", "0.1"),
        ("streaming.min_chunk_seconds", "6"),
        ("streaming.agreement_n", "1"),
        ("streaming.agreement_n", "5"),
        ("streaming.beam_size", "0"),
        ("streaming.beam_size", "11"),
        ("streaming.max_buffer_seconds", "4"),
        ("streaming.max_buffer_seconds", "121"),
        ("formatting.paragraph_pause_seconds", "-1"),
        ("formatting.paragraph_pause_seconds", "11"),
    ],
)
def test_streaming_out_of_range_rejected(tmp_path: pathlib.Path, key: str, value: str) -> None:
    p = tmp_path / "config.toml"
    p.write_text(f"[stenographer]\n{key} = {value}\n")
    with pytest.raises(ConfigError, match=key.replace(".", r"\.")):
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
