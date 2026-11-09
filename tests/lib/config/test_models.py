# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for the config loader."""

from __future__ import annotations

import logging
import pathlib
import warnings
from dataclasses import asdict, replace

import pytest

from stenographer.lib.config.defaults import default_toml
from stenographer.lib.config.errors import ConfigError
from stenographer.lib.config.models import AnalyticsConfig, Config, DeliveryConfig, LiveConfig
from stenographer.lib.config.paths import load_or_default
from stenographer.lib.platform import current_platform


def test_config_error_message():
    # Interpolate the path so the assertion follows pathlib's representation.
    path = pathlib.Path("/x")
    err = ConfigError(path, "asr.cpu_threads", "bad")
    assert str(err) == f"{path}: asr.cpu_threads: bad"
    assert err.key == "asr.cpu_threads"


def test_defaults_match_spec():
    d = Config.defaults()
    assert d.hotkey.binding == "KEY_RIGHTCTRL"
    assert d.hotkey.general_binding == "KEY_RIGHTALT"
    assert d.hotkey.device is None
    assert d.hotkey.cancel_binding == "KEY_ESC"
    assert d.hotkey.mode == "hybrid"
    assert d.hotkey.hybrid_threshold_seconds == 0.5
    assert d.audio.input_device is None
    assert d.audio.min_speech_rms == 0.0005
    assert d.audio.max_recording_seconds == 600
    assert d.asr.idle_unload_seconds == 900
    assert d.asr.cpu_threads == 0
    assert d.feedback.volume == 0.6
    assert d.feedback.mute is False
    assert d.feedback.overlay is True
    assert d.feedback.spectrum_floor_dbfs == -45.0
    assert d.feedback.sound_pack == "minimal-ui"
    assert d.feedback.log_level == "info"
    assert d.analytics == AnalyticsConfig(True, True)
    assert d.delivery == DeliveryConfig(True, True, 500)
    assert d.live == LiveConfig(False)


#: An ASR section as a Whisper-era release wrote it, with every removed key.
#: ``compute_type = "auto"`` was a valid CTranslate value the old
#: validator rejected; a removed key is not validated at all.
OLD_WHISPER_ASR = """\
[stenographer.asr]
model = "distil-whisper/distil-large-v3"
compute_type = "auto"          # int8 | int8_float16 | float16 | float32 | default
beam_size = 5
hotwords = "Kubernetes, Ada"   # proper nouns
initial_prompt = "Technical dictation."
vad_filter = false
silence_threshold = 0.4        # post-decode no-speech-probability gate
idle_unload_seconds = 120
cpu_threads = 4
"""


def test_an_old_whisper_config_loads_without_error_or_warning(tmp_path, caplog):
    p = tmp_path / "config.toml"
    p.write_text(OLD_WHISPER_ASR)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        cfg = Config.load(p)

    assert asdict(cfg.asr) == {"idle_unload_seconds": 120, "cpu_threads": 4}
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    assert p.read_text() == OLD_WHISPER_ASR


def test_write_default_round_trips(tmp_path):
    p = tmp_path / "config.toml"
    p.write_bytes(default_toml().encode("utf-8"))
    assert Config.load(p) == Config.defaults()


def test_default_template_takes_its_hotkey_device_comment_from_the_platform():
    """``/dev/input/event*`` is a Linux fact, so the host supplies that comment.

    Seen to FAIL against the hardcoded template (the rendered comment stayed
    "explicit /dev/input/event* path" while the platform said otherwise).
    """

    expected = current_platform().guidance().hotkey_device_comment
    rendered = default_toml()
    assert f'device = ""                    # {expected}\n' in rendered
    # The comment column is fixed so every annotated key still lines up.
    assert rendered.count("                    # ") == 1
    # Still valid, still the documented defaults.
    assert Config.loads(rendered) == Config.defaults()


def test_default_template_ships_the_default_mode_at_the_fixed_comment_column():
    """The written template must agree with the dataclass default and stay aligned.

    Seen to FAIL twice: with only ``HotkeyConfig.mode``/``Config.defaults``
    changed (the template still said ``mode = "hold"``), and with the template
    edited but not re-padded (the ``#`` moved off column 31).
    """

    line = next(text for text in default_toml().splitlines() if text.startswith("mode = "))
    assert line.startswith(f'mode = "{Config.defaults().hotkey.mode}"')
    assert line.index("#") == 31


def test_default_template_ships_the_two_universal_profile_bindings():
    text = default_toml()
    assert 'binding = "KEY_RIGHTCTRL"' in text
    assert 'general_binding = "KEY_RIGHTALT"' in text
    # No placeholder survived, and nothing else is left unrendered.
    assert "{" not in text


def test_loads_uses_supplied_path_in_errors():
    path = pathlib.Path("reviewed-config.toml")
    with pytest.raises(ConfigError) as exc:
        Config.loads("[stenographer.asr]\ncpu_threads = 65\n", path)
    assert exc.value.path == path


def test_load_or_default_writes_missing_file(tmp_path, monkeypatch):
    p = tmp_path / "nested" / "config.toml"
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(p))
    cfg = load_or_default()
    assert p.is_file()
    assert cfg == Config.defaults()


@pytest.mark.parametrize("value", ["false", "true", '"yes"'])
def test_retired_update_check_key_loads_and_has_no_effect(value):
    """Configs written before the update notice was removed keep the key."""

    cfg = Config.loads(f"[stenographer.feedback]\nupdate_check = {value}\n")

    assert cfg == Config.defaults()


def test_default_template_leaves_no_placeholder_unfilled():
    """Every ``{...}`` in ``assets/default_config.toml.in`` must be rendered.

    ``str.format`` raises on an unknown placeholder, but a stray brace that is
    not a field can survive rendering; either way the written config must hold
    none. Seen to FAIL with ``{typo}`` added to the template (``KeyError``).
    """

    rendered = default_toml()
    assert "{" not in rendered
    assert "}" not in rendered


def test_empty_string_is_unset(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[stenographer.hotkey]\ndevice = ""\ncancel_binding = ""\n'
        '[stenographer.audio]\ninput_device = ""\n'
    )
    cfg = Config.load(p)
    assert cfg.hotkey.device is None
    assert cfg.hotkey.cancel_binding is None
    assert cfg.audio.input_device is None


@pytest.mark.parametrize(
    ("toml_text", "section", "overrides"),
    [
        ('[stenographer.hotkey]\nbinding = "KEY_F8"', "hotkey", {"binding": "KEY_F8"}),
        ("[stenographer.asr]\ncpu_threads = 4", "asr", {"cpu_threads": 4}),
        ("[stenographer.asr]\ncpu_threads = 5", "asr", {"cpu_threads": 5}),
        ("[stenographer.feedback]\noverlay = false", "feedback", {"overlay": False}),
        *[
            (f'[stenographer.feedback]\nsound_pack = "{name}"', "feedback", {"sound_pack": name})
            for name in ("legacy", "warm-desk", "a", "a" * 64, "0-quiet")
        ],
        *[
            (
                f"[stenographer.feedback]\nspectrum_floor_dbfs = {floor}",
                "feedback",
                {"spectrum_floor_dbfs": float(floor)},
            )
            for floor in (-96, -45.5, -13)
        ],
        (
            "[stenographer.feedback]\nspectrum_floor_dbfs = ["
            + ", ".join(str(n) for n in range(-80, -62))
            + "]",
            "feedback",
            {
                "spectrum_floor_dbfs": (
                    -80.0,
                    -79.0,
                    -78.0,
                    -77.0,
                    -76.0,
                    -75.0,
                    -74.0,
                    -73.0,
                    -72.0,
                    -71.0,
                    -70.0,
                    -69.0,
                    -68.0,
                    -67.0,
                    -66.0,
                    -65.0,
                    -64.0,
                    -63.0,
                )
            },
        ),
        ('[stenographer.hotkey]\nmode = "toggle"', "hotkey", {"mode": "toggle"}),
        (
            '[stenographer.hotkey]\nmode = "hybrid"\nhybrid_threshold_seconds = 1.25',
            "hotkey",
            {"mode": "hybrid", "hybrid_threshold_seconds": 1.25},
        ),
        *[
            (f'[stenographer.feedback]\nlog_level = "{level}"', "feedback", {"log_level": "debug"})
            for level in ("debug", "DEBUG", "Debug")
        ],
        (
            "[stenographer.delivery]\ncopy_original = false\n"
            "restore_clipboard = false\nrestore_delay_ms = 0",
            "delivery",
            {"copy_original": False, "restore_clipboard": False, "restore_delay_ms": 0},
        ),
        ("[stenographer.live]\ndiarize_mic = true", "live", {"diarize_mic": True}),
    ],
)
def test_partial_overrides_preserve_other_defaults(toml_text, section, overrides):
    defaults = Config.defaults()
    assert Config.loads(toml_text) == replace(
        defaults, **{section: replace(getattr(defaults, section), **overrides)}
    )


def test_old_config_inherits_defaults_without_rewriting(tmp_path):
    path = tmp_path / "config.toml"
    content = "[stenographer.feedback]\nmute = true # preserved\n"
    path.write_text(content)
    defaults = Config.defaults()
    assert Config.load(path) == replace(defaults, feedback=replace(defaults.feedback, mute=True))
    assert path.read_text() == content


@pytest.mark.parametrize(
    ("toml_text", "key"),
    [
        *[
            (f'[stenographer.analytics]\n{key} = "true"', f"analytics.{key}")
            for key in ("enabled", "resource_profiling")
        ],
        ('[stenographer]\nasr = "medium"', "asr"),
        ("[stenographer]\nhotkey = 1", "hotkey"),
        ("[stenographer]\naudio = true", "audio"),
        ('[stenographer]\nfeedback = "x"', "feedback"),
        ("this is = = not valid", "<toml>"),
        *[
            (f"[stenographer.delivery]\n{line}", key)
            for line, key in [
                ("restore_delay_ms = -1", "delivery.restore_delay_ms"),
                ("restore_delay_ms = 60001", "delivery.restore_delay_ms"),
                ("restore_delay_ms = true", "delivery.restore_delay_ms"),
                ("restore_delay_ms = 1.5", "delivery.restore_delay_ms"),
                ('restore_delay_ms = "500"', "delivery.restore_delay_ms"),
                ('copy_original = "yes"', "delivery.copy_original"),
                ("restore_clipboard = 1", "delivery.restore_clipboard"),
            ]
        ],
        ("[stenographer]\ndelivery = 1", "delivery"),
        *[
            (f"[stenographer.live]\n{line}", "live.diarize_mic")
            for line in ('diarize_mic = "yes"', "diarize_mic = 1")
        ],
        ("[stenographer]\nlive = 1", "live"),
        ("[stenographer.asr]\ncpu_threads = 100\n", "asr.cpu_threads"),
        ('[stenographer.asr]\ncpu_threads = "x"\n', "asr.cpu_threads"),
        ("[stenographer.asr]\nidle_unload_seconds = -1\n", "asr.idle_unload_seconds"),
        ("[stenographer.feedback]\nvolume = -1\n", "feedback.volume"),
        ('[stenographer.feedback]\nmute = "no"\n', "feedback.mute"),
        ('[stenographer.feedback]\noverlay = "yes"\n', "feedback.overlay"),
        ('[stenographer.feedback]\nlog_level = "verbose"\n', "feedback.log_level"),
        ("[stenographer.feedback]\nlog_level = 10\n", "feedback.log_level"),
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
        ('[stenographer.hotkey]\nmode = "latch"\n', "hotkey.mode"),
        (
            "[stenographer.hotkey]\nhybrid_threshold_seconds = 0\n",
            "hotkey.hybrid_threshold_seconds",
        ),
        (
            "[stenographer.hotkey]\nhybrid_threshold_seconds = 5.5\n",
            "hotkey.hybrid_threshold_seconds",
        ),
        (
            '[stenographer.hotkey]\nhybrid_threshold_seconds = "0.5"\n',
            "hotkey.hybrid_threshold_seconds",
        ),
        ("[stenographer.audio]\nmax_recording_seconds = 0\n", "audio.max_recording_seconds"),
    ],
)
def test_out_of_range_or_wrong_type_raises(toml_text, key):
    with pytest.raises(ConfigError) as exc:
        Config.loads(toml_text)
    assert exc.value.key == key


def test_default_template_documents_the_delivery_section(tmp_path):
    p = tmp_path / "config.toml"
    p.write_bytes(default_toml().encode("utf-8"))
    text = p.read_text()

    assert "[stenographer.delivery]" in text
    assert "restore_delay_ms = 500" in text
    assert Config.load(p).delivery == DeliveryConfig()


def test_default_template_documents_the_live_section(tmp_path):
    p = tmp_path / "config.toml"
    p.write_bytes(default_toml().encode("utf-8"))
    text = p.read_text()

    assert "[stenographer.live]" in text
    assert "diarize_mic = false" in text
    assert Config.load(p).live == LiveConfig()


def test_invalid_utf8_is_a_file_config_error(tmp_path):
    path = tmp_path / "config.toml"
    path.write_bytes(b"\xff")
    with pytest.raises(ConfigError) as exc:
        Config.load(path)
    assert exc.value.path == path
    assert exc.value.key == "<file>"
    assert "UTF-8" in exc.value.reason


@pytest.mark.parametrize("field", ["binding", "general_binding", "cancel_binding"])
@pytest.mark.parametrize("chord", ["KEY_F8+", "KEY_NOT_A_REAL_KEY"])
def test_invalid_hotkey_chord_names_its_field(field, chord):
    with pytest.raises(ConfigError) as exc:
        Config.loads(f'[stenographer.hotkey]\n{field} = "{chord}"\n')
    assert exc.value.key == f"hotkey.{field}"


def test_vocabulary_invalid_entry_reports_position_and_type():
    with pytest.raises(ConfigError) as exc:
        Config.loads('[stenographer.refine]\nvocabulary = ["private term", 42]\n')
    assert exc.value.key == "refine.vocabulary"
    assert "term 2" in exc.value.reason
    assert "int" in exc.value.reason
    assert "private term" not in str(exc.value)


def test_invalid_refine_scheme_does_not_expose_credentials():
    with pytest.raises(ConfigError) as exc:
        Config.loads('[stenographer.refine]\nhost = "ftp://user:secret@example.com"\n')
    assert exc.value.key == "refine.host"
    assert "secret" not in str(exc.value)
