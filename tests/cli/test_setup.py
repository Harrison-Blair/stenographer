# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure decision, prompt parsing, and review/tryout rendering tests for setup.

Host prose is an input, not a constant: the tryout lines are handed a
``HostGuidance`` whose every word differs from the Linux provider's, so a
hardcoded command or service noun in ``setup.py`` cannot hide behind it.
"""

from __future__ import annotations

import dataclasses
import io
import pathlib

import pytest

from stenographer.cli import setup
from stenographer.cli.setup import (
    field_display,
    followup_exit_code,
    parse_bool,
    parse_choice,
    parse_number,
    parse_optional_string,
    parse_quick_review_action,
    parse_review_action,
    quick_review_lines,
    quick_tryout_lines,
    restart_eligible,
    review_lines,
)
from stenographer.config import Config
from stenographer.platform.base import HostGuidance

_CONFIG_PATH = pathlib.PurePosixPath("/tmp/custom.toml")

_GUIDANCE = HostGuidance(
    capability_labels={},
    capability_fix_hints={},
    clipboard_fix_hints={},
    clipboard_fix_hint_default="enable a pasteboard",
    overlay_backend_labels={},
    overlay_fix_hints={},
    overlay_fix_hint_default="no display backend",
    service_noun="host agent",
    service_name="steno-agent",
    service_installer="steno-agent install",
    service_unknown_detail="cannot query the agent manager",
    service_start_command="steno-agent start",
    service_restart_command="steno-agent restart",
    service_log_command="steno-agent logs -f",
    hotkey_device_comment="device id; empty auto-detects",
    run_with_config=lambda path: f"STENO_CONFIG={path} stenographer run",
)


def _tryout(**overrides) -> list[str]:
    state = {
        "custom_config": False,
        "service_enabled": "enabled",
        "service_active": "active",
        "restart_pending": False,
    }
    config = overrides.pop("config", Config.defaults())
    state.update(overrides)
    return quick_tryout_lines(config, _CONFIG_PATH, _GUIDANCE, **state)


def test_optional_string_retains_clears_and_replaces():
    assert parse_optional_string("", "current") == "current"
    assert parse_optional_string(" clear ", "current") is None
    assert parse_optional_string("replacement", None) == "replacement"


def test_choice_retains_and_is_case_insensitive():
    assert parse_choice("", "hold", ("hold", "toggle")) == "hold"
    assert parse_choice("TOGGLE", "hold", ("hold", "toggle")) == "toggle"
    with pytest.raises(ValueError, match="choose one of"):
        parse_choice("hybrid", "hold", ("hold", "toggle"))


@pytest.mark.parametrize(("answer", "expected"), [("yes", True), ("N", False), ("", True)])
def test_bool_answers(answer, expected):
    assert parse_bool(answer, True) is expected


def test_bool_rejects_ambiguous_answer():
    with pytest.raises(ValueError, match="yes or no"):
        parse_bool("maybe", False)


def test_number_retains_and_enforces_type_and_range():
    assert parse_number("", 3, minimum=1, maximum=10, integer=True) == 3
    assert parse_number("4", 3, minimum=1, maximum=10, integer=True) == 4
    assert parse_number(".25", 0.5, minimum=0.0, maximum=1.0) == 0.25
    with pytest.raises(ValueError, match="must be in"):
        parse_number("11", 3, minimum=1, maximum=10, integer=True)
    with pytest.raises(ValueError, match="integer"):
        parse_number("1.5", 3, minimum=1, maximum=10, integer=True)


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("", "save"),
        ("cancel", "cancel"),
        ("1", "hotkey"),
        ("2", "audio"),
        ("3", "asr"),
        ("4", "feedback"),
    ],
)
def test_review_actions(answer, expected):
    assert parse_review_action(answer) == expected


def test_review_rejects_unknown_action():
    with pytest.raises(ValueError, match="Save, Cancel"):
        parse_review_action("later")


@pytest.mark.parametrize(
    ("answer", "expected"), [("", "save"), ("S", "save"), ("cancel", "cancel")]
)
def test_quick_review_actions(answer, expected):
    assert parse_quick_review_action(answer) == expected


def test_quick_review_rejects_reedit_actions():
    with pytest.raises(ValueError, match="Save or Cancel"):
        parse_quick_review_action("audio")


@pytest.mark.parametrize(
    ("changed", "custom", "missing", "active", "expected"),
    [
        (True, False, False, "active", True),
        (False, False, False, "active", False),
        (True, True, False, "active", False),
        (True, False, True, "active", False),
        (True, False, False, "inactive", False),
        (True, False, False, None, False),
    ],
)
def test_restart_eligibility(changed, custom, missing, active, expected):
    assert (
        restart_eligible(
            config_changed=changed,
            custom_config=custom,
            missing_required=missing,
            service_active=active,
        )
        is expected
    )


@pytest.mark.parametrize(
    ("operational", "missing", "expected"),
    [(False, False, 0), (False, True, 78), (True, False, 1), (True, True, 1)],
)
def test_followup_exit_precedence(operational, missing, expected):
    assert followup_exit_code(operational_failure=operational, missing_required=missing) == expected


def test_tryout_sends_a_custom_config_path_to_a_foreground_run():
    lines = _tryout(custom_config=True)

    assert lines[0] == "\nTry a real dictation"
    assert lines[1] == (
        "Run `STENO_CONFIG=/tmp/custom.toml stenographer run` in a terminal; "
        "the standard service was not changed."
    )
    assert lines[-1] == (
        "Watch that foreground command for logs; the standard service log is `steno-agent logs -f`."
    )


def test_tryout_asks_for_a_restart_before_anything_else_when_one_is_pending():
    lines = _tryout(restart_pending=True)

    assert lines[1] == "Apply the saved configuration first with `steno-agent restart`."


def test_tryout_reports_an_active_service_as_ready():
    assert _tryout()[1] == "steno-agent is active and ready for a tryout."


def test_tryout_offers_the_installer_when_the_service_is_not_installed():
    lines = _tryout(service_enabled=None, service_active="inactive")

    assert lines[1] == (
        "The service is not installed. Run `stenographer run` in a terminal, "
        "or install it with `steno-agent install`."
    )


def test_tryout_points_an_installed_but_stopped_service_at_the_start_command():
    lines = _tryout(service_enabled="disabled", service_active="inactive")

    assert lines[1] == (
        "The service is inactive. Start it with `steno-agent start`; setup did not start it."
    )


def test_tryout_falls_back_to_a_foreground_run_when_the_state_is_unknown():
    lines = _tryout(service_enabled=None, service_active=None)

    assert lines[1] == (
        "The user-service state could not be determined. Run `stenographer run` "
        "in a terminal to try the configuration."
    )


def test_tryout_describes_a_hold_binding_as_held_and_logs_the_service():
    config = Config.defaults()
    lines = _tryout(config=config)

    assert lines[-2] == "Focus a text field, hold KEY_RIGHTCTRL, speak, then release it."
    assert lines[-1] == "Follow service logs with `steno-agent logs -f`."


def test_tryout_describes_a_toggle_binding_as_pressed_twice():
    defaults = Config.defaults()
    config = dataclasses.replace(
        defaults, hotkey=dataclasses.replace(defaults.hotkey, mode="toggle", binding="KEY_F9")
    )

    assert _tryout(config=config)[-2] == (
        "Focus a text field, press KEY_F9, speak, then press it again."
    )


def test_field_display_names_unset_values_and_calibrated_profiles():
    assert field_display(None, "device") == "automatic/unset"
    assert field_display(-45.0, "spectrum_floor_dbfs") == "-45.0"
    assert field_display((-45.0,) * 18, "spectrum_floor_dbfs") == "calibrated 18-band profile"
    assert field_display((1.0, 2.0), "hotwords") == "(1.0, 2.0)"


def test_full_review_lists_every_section_and_field():
    assert review_lines(Config.defaults()) == [
        "\nReview",
        "[hotkey]",
        "  binding = KEY_RIGHTCTRL",
        "  device = automatic/unset",
        "  mode = hold",
        "[audio]",
        "  input_device = automatic/unset",
        "  min_speech_rms = 0.0005",
        "  max_recording_seconds = 600",
        "[asr]",
        "  model = Systran/faster-whisper-medium.en",
        "  compute_type = int8",
        "  beam_size = 1",
        "  hotwords = automatic/unset",
        "  initial_prompt = automatic/unset",
        "  vad_filter = True",
        "  silence_threshold = 0.6",
        "  idle_unload_seconds = 900",
        "  cpu_threads = 0",
        "[feedback]",
        "  volume = 0.6",
        "  mute = False",
        "  overlay = True",
        "  update_check = True",
        "  spectrum_floor_dbfs = -45.0",
        "  sound_pack = minimal-ui",
        "  log_level = info",
    ]


def test_full_review_names_a_calibrated_profile_instead_of_eighteen_numbers():
    defaults = Config.defaults()
    config = dataclasses.replace(
        defaults,
        feedback=dataclasses.replace(defaults.feedback, spectrum_floor_dbfs=(-52.0,) * 18),
    )

    assert "  spectrum_floor_dbfs = calibrated 18-band profile" in review_lines(config)


def test_quick_review_lists_only_the_keys_the_quick_wizard_edits():
    lines = quick_review_lines(Config.defaults())

    assert lines == [
        "\nQuick setup review",
        "  hotkey.device = automatic/unset",
        "  hotkey.binding = KEY_RIGHTCTRL",
        "  hotkey.mode = hold",
        "  audio.input_device = automatic/unset",
        "  feedback.volume = 0.6",
        "  feedback.mute = False",
        "  feedback.overlay = True",
        "  feedback.update_check = True",
        "  feedback.sound_pack = minimal-ui",
        "  feedback.spectrum_floor_dbfs = -45.0",
        "Audio-gate, recording-limit, and all ASR settings will be retained unchanged.",
    ]


def test_quick_review_names_a_calibrated_profile_like_the_full_review():
    defaults = Config.defaults()
    config = dataclasses.replace(
        defaults,
        feedback=dataclasses.replace(defaults.feedback, spectrum_floor_dbfs=(-52.0,) * 18),
    )

    assert "  feedback.spectrum_floor_dbfs = calibrated 18-band profile" in quick_review_lines(
        config
    )


def test_setup_requires_an_interactive_terminal():
    stderr = io.StringIO()
    assert setup.run(stdin=io.StringIO(), stdout=io.StringIO(), stderr=stderr) == 2
    assert "requires an interactive terminal" in stderr.getvalue()


def test_setup_applies_loaded_then_reviewed_log_levels_before_followup_work(monkeypatch, tmp_path):
    from stenographer.cli.setup_config import SaveResult
    from stenographer.utils import logging_setup

    events: list[str] = []
    defaults = Config.defaults()
    loaded = dataclasses.replace(
        defaults,
        feedback=dataclasses.replace(defaults.feedback, log_level="warning"),
    )
    reviewed = dataclasses.replace(
        loaded,
        feedback=dataclasses.replace(loaded.feedback, log_level="debug"),
    )

    class Document:
        path = tmp_path / "config.toml"
        config = loaded

        def save(self, config):
            assert config is reviewed
            events.append("save")
            return SaveResult(False, self.path)

    monkeypatch.setattr(setup, "require_interactive", lambda *args, **kwargs: None)
    monkeypatch.setattr(setup, "load_document", lambda *args, **kwargs: Document())
    monkeypatch.setattr(
        setup,
        "_wizard",
        lambda *args, **kwargs: events.append("wizard") or reviewed,
    )
    monkeypatch.setattr(
        setup,
        "_guided_setup",
        lambda *args, **kwargs: events.append("guided") or 0,
    )
    monkeypatch.setattr(
        logging_setup,
        "apply_stderr_level",
        lambda level: events.append(f"level:{level}"),
    )

    assert setup.run(stdin=io.StringIO(), stdout=io.StringIO(), stderr=io.StringIO()) == 0
    assert events == ["level:warning", "wizard", "save", "level:debug", "guided"]


def test_setup_does_not_apply_a_level_when_loading_fails(monkeypatch):
    from stenographer.utils import logging_setup

    levels: list[str] = []
    monkeypatch.setattr(setup, "require_interactive", lambda *args, **kwargs: None)
    monkeypatch.setattr(setup, "load_document", lambda *args, **kwargs: 78)
    monkeypatch.setattr(logging_setup, "apply_stderr_level", levels.append)

    assert setup.run(stdin=io.StringIO(), stdout=io.StringIO(), stderr=io.StringIO()) == 78
    assert levels == []


def test_setup_save_failure_keeps_the_loaded_level(monkeypatch, tmp_path):
    from stenographer.cli.setup_config import ConfigPersistenceError
    from stenographer.utils import logging_setup

    levels: list[str] = []
    defaults = Config.defaults()
    loaded = dataclasses.replace(
        defaults,
        feedback=dataclasses.replace(defaults.feedback, log_level="warning"),
    )
    reviewed = dataclasses.replace(
        loaded,
        feedback=dataclasses.replace(loaded.feedback, log_level="debug"),
    )

    class Document:
        path = tmp_path / "config.toml"
        config = loaded

        def save(self, config):
            assert config is reviewed
            raise ConfigPersistenceError("save failed")

    monkeypatch.setattr(setup, "require_interactive", lambda *args, **kwargs: None)
    monkeypatch.setattr(setup, "load_document", lambda *args, **kwargs: Document())
    monkeypatch.setattr(setup, "_wizard", lambda *args, **kwargs: reviewed)
    monkeypatch.setattr(logging_setup, "apply_stderr_level", levels.append)

    assert setup.run(stdin=io.StringIO(), stdout=io.StringIO(), stderr=io.StringIO()) == 1
    assert levels == ["warning"]
