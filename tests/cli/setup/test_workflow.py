# SPDX-License-Identifier: GPL-3.0-or-later
"""Decision, prompt, wizard, and guided-setup tests for the setup workflow.

The first half is pure: parsing, restart policy, and review/tryout rendering.
The second half drives the interactive wizard for real over a ``Console`` bound
to string streams, so every prompt, retry, and section edit is exercised as the
user would meet it. Hardware never is: the two device enumerators, the spectrum
estimator, and the binding capture are supplied at their own module seams, so
nothing here opens a microphone, ``/dev/input``, or ``/dev/uinput``.

Host prose is an input, not a constant: the tryout lines are handed a
``HostGuidance`` whose every word differs from the Linux provider's, so a
hardcoded command or service noun in ``setup.py`` cannot hide behind it.
"""

from __future__ import annotations

import dataclasses
import io
import pathlib

import pytest

from stenographer.cli.setup import workflow as setup
from stenographer.cli.setup.default import write_default
from stenographer.cli.setup.workflow import (
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
from stenographer.cli.shared.capabilities import Capabilities
from stenographer.cli.shared.console import Console
from stenographer.lib.config.defaults import default_toml
from stenographer.lib.config.models import Config
from stenographer.lib.platform.host_guidance import HostGuidance

_CONFIG_PATH = pathlib.PurePosixPath("/tmp/custom.toml")

_GUIDANCE = HostGuidance(
    capability_labels={},
    capability_fix_hints={},
    clipboard_fix_hints={},
    clipboard_fix_hint_default="enable a pasteboard",
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
    assert parse_choice("", "hold", ("hold", "toggle", "hybrid")) == "hold"
    assert parse_choice("TOGGLE", "hold", ("hold", "toggle", "hybrid")) == "toggle"
    assert parse_choice("HYBRID", "hold", ("hold", "toggle", "hybrid")) == "hybrid"
    with pytest.raises(ValueError, match="choose one of"):
        parse_choice("latch", "hold", ("hold", "toggle", "hybrid"))


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
        ("5", "refine"),
        ("refine", "refine"),
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
    defaults = Config.defaults()
    config = dataclasses.replace(defaults, hotkey=dataclasses.replace(defaults.hotkey, mode="hold"))
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


def test_tryout_describes_a_hybrid_binding_as_tapped_or_held():
    defaults = Config.defaults()
    config = dataclasses.replace(
        defaults, hotkey=dataclasses.replace(defaults.hotkey, mode="hybrid", binding="KEY_F9")
    )

    assert _tryout(config=config)[-2] == (
        "Focus a text field, tap KEY_F9 to latch (tap again to stop), "
        "or hold it, speak, and release."
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
        "  cancel_binding = KEY_ESC",
        "  mode = hybrid",
        "  hybrid_threshold_seconds = 0.5",
        "[audio]",
        "  input_device = automatic/unset",
        "  min_speech_rms = 0.0005",
        "  max_recording_seconds = 600",
        "[asr]",
        "  model = dropbox-dash/faster-whisper-large-v3-turbo",
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
        "[refine]",
        "  enabled = False",
        "  host = http://127.0.0.1:11434",
        "  model = gemma4:e2b",
        "  min_words = 10",
        "  structured_output = False",
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
        "  hotkey.mode = hybrid",
        "  audio.input_device = automatic/unset",
        "  feedback.volume = 0.6",
        "  feedback.mute = False",
        "  feedback.overlay = True",
        "  feedback.update_check = True",
        "  feedback.sound_pack = minimal-ui",
        "  feedback.spectrum_floor_dbfs = -45.0",
        "  refine.enabled = False",
        "  refine.model = gemma4:e2b",
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
    from stenographer.lib.config.save_result import SaveResult
    from stenographer.lib.logging import pipeline as logging_setup

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
    from stenographer.lib.logging import pipeline as logging_setup

    levels: list[str] = []
    monkeypatch.setattr(setup, "require_interactive", lambda *args, **kwargs: None)
    monkeypatch.setattr(setup, "load_document", lambda *args, **kwargs: 78)
    monkeypatch.setattr(logging_setup, "apply_stderr_level", levels.append)

    assert setup.run(stdin=io.StringIO(), stdout=io.StringIO(), stderr=io.StringIO()) == 78
    assert levels == []


def test_setup_save_failure_keeps_the_loaded_level(monkeypatch, tmp_path):
    from stenographer.lib.config.errors import ConfigPersistenceError
    from stenographer.lib.logging import pipeline as logging_setup

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


def test_write_default_creates_the_annotated_template(tmp_path, monkeypatch):
    """Seen to FAIL against a ``write_default`` with its ``report_save`` call
    dropped (the file appeared but nothing was printed)."""
    path = tmp_path / "nested" / "config.toml"
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(path))
    out, err = io.StringIO(), io.StringIO()

    assert write_default(stdout=out, stderr=err) == 0

    assert path.read_text(encoding="utf-8") == default_toml()
    assert f"Wrote the default configuration to {path.resolve()}" in out.getvalue()
    assert err.getvalue() == ""


def test_write_default_leaves_an_identical_file_untouched(tmp_path, monkeypatch):
    """Seen to FAIL against a writer calling ``Config.write_default`` directly
    (identical bytes were rewritten).

    The configured path is deliberately un-normalized, so the report line is
    only correct if it names the resolved target the save actually inspected.
    """
    (tmp_path / "sub").mkdir()
    path = tmp_path / "sub" / ".." / "config.toml"
    # Bytes, not text mode: Windows would rewrite the template's newlines as CRLF,
    # and the preservation layer compares bytes.
    path.write_bytes(default_toml().encode("utf-8"))
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(path))
    before = path.stat().st_mtime_ns
    out = io.StringIO()

    assert write_default(stdout=out, stderr=io.StringIO()) == 0

    assert path.stat().st_mtime_ns == before
    assert list(tmp_path.glob("config.toml.bak-*")) == []
    assert f"{path.resolve()} already matches the defaults" in out.getvalue()


def test_write_default_backs_up_a_customized_config_and_reports_it(tmp_path, monkeypatch):
    """Seen to FAIL against a writer that bypassed the preservation layer (the
    previous configuration was replaced with no backup and no report line)."""
    path = tmp_path / "config.toml"
    original = '# mine\n[stenographer.hotkey]\nmode = "toggle"\n'
    path.write_text(original, encoding="utf-8")
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(path))
    out = io.StringIO()

    assert write_default(stdout=out, stderr=io.StringIO()) == 0

    backups = list(tmp_path.glob("config.toml.bak-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == original
    assert f"Backup: {backups[0]}" in out.getvalue()
    assert path.read_text(encoding="utf-8") == default_toml()


def test_write_default_replaces_a_config_too_broken_to_load(tmp_path, monkeypatch):
    """The repair path parses none of the current bytes.

    Seen to FAIL against a writer built on ``load_document`` (it reported
    ``<toml>: malformed TOML`` and exited 78 without writing anything)."""
    path = tmp_path / "config.toml"
    path.write_bytes(b"[stenographer.hotkey\nbinding = \n")
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(path))

    assert write_default(stdout=io.StringIO(), stderr=io.StringIO()) == 0

    assert path.read_text(encoding="utf-8") == default_toml()
    assert len(list(tmp_path.glob("config.toml.bak-*"))) == 1


class _Keys:
    """The project's own portable key vocabulary, without any device access."""

    def code(self, name: str) -> int:
        from stenographer.lib.hotkey.keycodes import KEY_CODES

        return KEY_CODES[name]

    def name(self, code: int) -> str | None:
        from stenographer.lib.hotkey.keycodes import CODE_NAMES

        return CODE_NAMES.get(code)


def _console(answers: str = "") -> Console:
    return Console(io.StringIO(answers), io.StringIO(), io.StringIO())


@pytest.fixture
def key_vocabulary(monkeypatch):
    """Resolve bindings through the core key table rather than a real device."""

    from stenographer.lib import platform as platform_module

    class Plat:
        def keys(self):
            return _Keys()

    monkeypatch.setattr(platform_module, "current_platform", Plat)
    return Plat


def test_prompt_string_keeps_the_current_value_on_enter_and_replaces_it_otherwise():
    keep = _console("\n")
    assert setup._prompt_string(keep, "Model", "medium.en") == "medium.en"
    assert keep.stdout.getvalue() == "Model [medium.en]: "

    replace = _console("  small.en  \n")
    assert setup._prompt_string(replace, "Model", "medium.en") == "small.en"


def test_prompt_optional_names_the_clear_token_and_unsets_on_it():
    console = _console("clear\n")

    assert setup._prompt_optional(console, "Hotwords", "kubernetes") is None
    assert console.stdout.getvalue() == ("Hotwords [kubernetes; Enter keeps, 'clear' unsets]: ")


def test_prompt_optional_shows_an_unset_value_as_automatic():
    console = _console("evdev\n")

    assert setup._prompt_optional(console, "Hotwords", None) == "evdev"
    assert "Hotwords [automatic/unset;" in console.stdout.getvalue()


def test_prompt_choice_lists_every_choice_and_retries_until_one_matches():
    console = _console("latch\ntoggle\n")

    choices = ("hold", "toggle", "hybrid")

    assert setup._prompt_choice(console, "Trigger mode", "hold", choices) == "toggle"
    assert console.stdout.getvalue().startswith("Trigger mode (hold/toggle/hybrid) [hold]: ")
    assert console.stderr.getvalue() == "stenographer: choose one of: hold, toggle, hybrid\n"


@pytest.mark.parametrize(
    ("current", "marker", "answer", "expected"),
    [(True, "[yes]", "\n", True), (False, "[no]", "y\n", True)],
)
def test_prompt_bool_marks_the_current_answer(current, marker, answer, expected):
    console = _console(answer)

    assert setup._prompt_bool(console, "VAD filter", current) is expected
    assert console.stdout.getvalue() == f"VAD filter (yes/no) {marker}: "


def test_prompt_number_states_its_bounds_and_retries_until_one_fits():
    console = _console("99\n7\n")

    assert setup._prompt_number(console, "Beam size", 1, 1, 10, integer=True) == 7
    assert console.stdout.getvalue().startswith("Beam size [1; 1..10]: ")
    assert console.stderr.getvalue() == "stenographer: must be in [1, 10]\n"


def test_prompt_sound_pack_lists_the_discovered_packs_and_selects_by_number(tmp_path):
    console = _console("2\n")

    assert setup._prompt_sound_pack(console, "minimal-ui", tmp_path) == "warm-desk"

    stdout = console.stdout.getvalue()
    assert stdout.startswith("Sound packs:\n  1. legacy\n  2. warm-desk\n")
    assert "Sound pack [minimal-ui; Enter keeps, number/name selects]: " in stdout


_DEVICES = [("1", "1: USB mic"), ("2", "2: Studio interface")]


@pytest.mark.parametrize(
    ("answer", "expected"),
    [("\n", "1"), ("2\n", "2"), ("auto\n", None), ("clear\n", None), ("hw:9,0\n", "hw:9,0")],
)
def test_prompt_device_number_selects_auto_unsets_and_free_text_passes_through(answer, expected):
    console = _console(answer)

    assert setup._prompt_device(console, "Audio input", "1", _DEVICES) == expected

    stdout = console.stdout.getvalue()
    assert "Audio input devices (automatic selection is always available):" in stdout
    assert "  1. 1: USB mic" in stdout
    assert "  2. 2: Studio interface" in stdout


def test_prompt_device_still_offers_manual_entry_when_nothing_was_found():
    console = _console("hw:2,0\n")

    assert setup._prompt_device(console, "Hotkey", None, []) == "hw:2,0"

    stdout = console.stdout.getvalue()
    assert "  (no selectable devices found; manual entry is still available)" in stdout
    assert "Hotkey [automatic/unset;" in stdout


def test_binding_parsing_rejects_an_empty_and_an_unknown_key(key_vocabulary):
    with pytest.raises(ValueError, match="binding must be non-empty"):
        setup._parse_binding("   ")
    with pytest.raises(ValueError, match="unknown key"):
        setup._parse_binding("KEY_NOT_A_KEY")
    assert setup._parse_binding(" KEY_LEFTCTRL+KEY_F9 ") == "KEY_LEFTCTRL+KEY_F9"


def test_typed_binding_retries_until_the_chord_parses(key_vocabulary):
    console = _console("KEY_NOPE\nKEY_F9\n")

    assert setup._prompt_typed_binding(console, "KEY_RIGHTCTRL") == "KEY_F9"
    assert console.stdout.getvalue() == "Binding [KEY_RIGHTCTRL]: Binding [KEY_RIGHTCTRL]: "
    assert "unknown key 'KEY_NOPE'" in console.stderr.getvalue()


def test_typed_binding_enter_keeps_the_current_chord(key_vocabulary):
    console = _console("\n")

    assert setup._prompt_typed_binding(console, "KEY_RIGHTCTRL") == "KEY_RIGHTCTRL"


@pytest.fixture
def device_menus(monkeypatch):
    """Offer fixed device menus instead of enumerating PortAudio or /dev/input."""

    monkeypatch.setattr(setup, "_hotkey_devices", lambda: [("event3", "event3: Keyboard")])
    monkeypatch.setattr(setup, "_audio_devices", lambda: [("1", "1: USB mic")])


def test_edit_hotkey_asks_binding_device_mode_and_threshold(key_vocabulary, device_menus):
    console = _console("KEY_F9\n1\ntoggle\n1.25\n")

    hotkey = setup._edit_hotkey(console, Config.defaults()).hotkey

    assert hotkey.binding == "KEY_F9"
    assert hotkey.device == "event3"
    assert hotkey.mode == "toggle"
    assert hotkey.hybrid_threshold_seconds == 1.25
    assert "  1. event3: Keyboard" in console.stdout.getvalue()


def test_edit_audio_asks_the_device_gate_and_recording_limit(device_menus):
    console = _console("1\n0.002\n120\n")

    audio = setup._edit_audio(console, Config.defaults()).audio

    assert audio.input_device == "1"
    assert audio.min_speech_rms == 0.002
    assert audio.max_recording_seconds == 120
    assert "min_speech_rms is the pre-decode energy gate; 0 disables it." in (
        console.stdout.getvalue()
    )


def test_edit_asr_asks_every_recognition_key_in_order():
    console = _console("small.en\nfloat16\n5\nevdev\nA prompt.\nno\n0.25\n60\n4\n")

    asr = setup._edit_asr(console, Config.defaults()).asr

    assert asr.model == "small.en"
    assert asr.compute_type == "float16"
    assert asr.beam_size == 5
    assert asr.hotwords == "evdev"
    assert asr.initial_prompt == "A prompt."
    assert asr.vad_filter is False
    assert asr.silence_threshold == 0.25
    assert asr.idle_unload_seconds == 60
    assert asr.cpu_threads == 4


def test_choose_floor_keeps_the_current_response_without_touching_the_microphone():
    console = _console("keep\n")

    assert setup._choose_floor(console, Config.defaults(), -45.0) == -45.0
    assert console.stdout.getvalue() == ("Spectrum response (automatic/keep/manual) [automatic]: ")


def test_choose_floor_defaults_to_keeping_an_existing_calibrated_profile():
    profile = (-52.0,) * 18
    console = _console("\n")

    assert setup._choose_floor(console, Config.defaults(), profile) == profile
    assert "[keep]: " in console.stdout.getvalue()


def test_choose_floor_manual_asks_for_a_bounded_dbfs_value():
    console = _console("manual\n-5\n-61.5\n")

    assert setup._choose_floor(console, Config.defaults(), -45.0) == -61.5
    assert "Spectrum floor dBFS [-45.0; -96.0..-13.0]: " in console.stdout.getvalue()
    assert console.stderr.getvalue() == "stenographer: must be in [-96.0, -13.0]\n"


def test_manual_floor_offers_a_scalar_default_when_a_profile_is_current():
    from stenographer.overlay.spectrum.analysis import DEFAULT_SPECTRUM_FLOOR_DBFS

    console = _console("\n")

    assert setup._manual_floor(console, (-52.0,) * 18) == DEFAULT_SPECTRUM_FLOOR_DBFS
    assert f"Spectrum floor dBFS [{DEFAULT_SPECTRUM_FLOOR_DBFS};" in console.stdout.getvalue()


def test_quick_feedback_section_skips_calibration_when_the_overlay_is_off(tmp_path):
    console = _console("0.9\n\nno\n\n\n")

    config = setup._edit_feedback_section(
        console,
        Config.defaults(),
        tmp_path,
        notice=("IMPORTANT: bars only.",),
        skip_floor_without_overlay=True,
        ask_log_level=False,
    )

    assert config.feedback.volume == 0.9
    assert config.feedback.overlay is False
    assert config.feedback.spectrum_floor_dbfs == Config.defaults().feedback.spectrum_floor_dbfs
    stdout = console.stdout.getvalue()
    assert "IMPORTANT: bars only." in stdout
    assert "Overlay is disabled, so display-spectrum calibration was skipped." in stdout
    assert "Log level" not in stdout
    assert "Spectrum response" not in stdout


def test_full_feedback_section_asks_the_log_level_and_the_spectrum_response(tmp_path):
    console = _console("\n\n\n\n\ndebug\nkeep\n")

    config = setup._edit_feedback_section(
        console,
        Config.defaults(),
        tmp_path,
        notice=("IMPORTANT: bars only.",),
        skip_floor_without_overlay=False,
        ask_log_level=True,
    )

    assert config.feedback.log_level == "debug"
    stdout = console.stdout.getvalue()
    assert "Log level (debug/error/info/warning) [info]: " in stdout
    assert "Spectrum response" in stdout


#: Enter keeps every value; the wizard asks five sections then the review.
#: The trailing blank answers "Enable transcript refinement", which defaults to
#: no and so never reaches the Ollama probe.
_KEEP_EVERYTHING = "\n" * 22 + "keep\n" + "\n"


def test_wizard_walks_every_section_then_saves_the_reviewed_configuration(
    key_vocabulary,
    device_menus,
    tmp_path,
):
    console = _console(
        "KEY_F9\n1\ntoggle\n\n"  # hotkey
        "auto\n\n120\n"  # audio
        "\n\n5\nevdev\n\nno\n\n\n\n"  # asr
        "0.9\n\n\n\nlegacy\ndebug\nkeep\n"  # feedback
        "\n"  # refine: stay disabled
        "\n"  # review: save
    )

    config = setup._wizard(console, Config.defaults(), tmp_path)

    assert config.hotkey.binding == "KEY_F9"
    assert config.hotkey.device == "event3"
    assert config.hotkey.mode == "toggle"
    assert config.audio.input_device is None
    assert config.audio.max_recording_seconds == 120
    assert config.asr.beam_size == 5
    assert config.asr.hotwords == "evdev"
    assert config.asr.vad_filter is False
    assert config.feedback.volume == 0.9
    assert config.feedback.sound_pack == "legacy"
    assert config.feedback.log_level == "debug"
    assert "\nReview" in console.stdout.getvalue()


def test_wizard_reopens_the_section_the_reviewer_names(key_vocabulary, device_menus, tmp_path):
    console = _console(
        _KEEP_EVERYTHING
        + "2\n"  # review: re-edit audio
        + "1\n\n90\n"  # audio again
        + "\n"  # review: save
    )

    config = setup._wizard(console, Config.defaults(), tmp_path)

    assert config.audio.input_device == "1"
    assert config.audio.max_recording_seconds == 90
    assert console.stdout.getvalue().count("\nReview") == 2


def test_wizard_cancel_raises_so_nothing_is_saved(key_vocabulary, device_menus, tmp_path):
    console = _console(_KEEP_EVERYTHING + "c\n")

    with pytest.raises(setup.SetupCancelledError):
        setup._wizard(console, Config.defaults(), tmp_path)


@pytest.mark.parametrize(
    ("answers", "expected"),
    [("keep\n", "KEY_RIGHTCTRL"), ("type\nKEY_F9\n", "KEY_F9")],
)
def test_capture_or_choose_binding_keep_and_type_arms(key_vocabulary, answers, expected):
    console = _console(answers)

    result = setup._capture_or_choose_binding(
        console,
        "KEY_RIGHTCTRL",
        None,
        new_config=False,
    )

    assert result == expected
    assert "Binding (capture/keep/type) [keep]: " in console.stdout.getvalue()


def test_capture_is_the_default_offer_for_a_brand_new_configuration(key_vocabulary):
    console = _console("keep\n")

    setup._capture_or_choose_binding(console, "KEY_RIGHTCTRL", None, new_config=True)

    assert "Binding (capture/keep/type) [capture]: " in console.stdout.getvalue()


def test_audio_device_menu_comes_from_the_shared_portaudio_enumeration(monkeypatch):
    from stenographer.lib.audio import probe
    from stenographer.lib.audio.device_query import DeviceQuery

    monkeypatch.setattr(
        probe,
        "query_devices",
        lambda: DeviceQuery(
            devices=(
                {"name": "HDMI out", "max_input_channels": 0},
                {"name": "USB mic", "max_input_channels": 1},
            )
        ),
    )

    assert setup._audio_devices() == [("1", "1: USB mic")]


def test_hotkey_device_menu_comes_from_the_platform_provider(monkeypatch):
    from stenographer.lib import platform as platform_module

    class Plat:
        def hotkey_devices(self):
            return [("event3", "event3: Keyboard")]

    monkeypatch.setattr(platform_module, "current_platform", Plat)

    assert setup._hotkey_devices() == [("event3", "event3: Keyboard")]


@pytest.fixture
def calibrator(monkeypatch):
    """Supply calibration results at the estimator seam, never a real microphone."""

    from stenographer.overlay.spectrum import calibration

    def install(*results):
        pending = list(results)

        def calibrate(device, *, on_countdown, on_voice_prompt, **kwargs):
            on_countdown(3)
            on_countdown(0)
            on_voice_prompt()
            outcome = pending.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        monkeypatch.setattr(calibration, "calibrate_spectrum_profile", calibrate)
        return pending

    return install


def test_automatic_calibration_accepted_returns_the_learned_profile(calibrator):
    profile = (-62.0,) * 18
    calibrator(profile)
    console = _console("accept\n")

    assert setup._automatic_floor(console, Config.defaults(), -45.0) == profile

    stdout = console.stdout.getvalue()
    assert "Keep the room quiet." in stdout
    assert "Stay silent — recording starts in 3..." in stdout
    assert "Recording room noise now." in stdout
    assert "Speak normally now for three seconds so visibility can be verified." in stdout
    assert "Background profile learned and normal voice visibility verified." in stdout


def test_automatic_calibration_retries_before_accepting(calibrator):
    second = (-58.0,) * 18
    calibrator((-70.0,) * 18, second)
    console = _console("retry\naccept\n")

    assert setup._automatic_floor(console, Config.defaults(), -45.0) == second


def test_automatic_calibration_can_hand_over_to_the_manual_value(calibrator):
    calibrator((-70.0,) * 18)
    console = _console("manual\n-61.5\n")

    assert setup._automatic_floor(console, Config.defaults(), -45.0) == -61.5


def test_automatic_calibration_keep_retains_the_current_response(calibrator):
    calibrator((-70.0,) * 18)
    console = _console("keep\n")

    assert setup._automatic_floor(console, Config.defaults(), -45.0) == -45.0


def test_a_rejected_capture_is_reported_as_rejected_and_may_be_kept(calibrator):
    from stenographer.overlay.spectrum.errors import CalibrationError

    calibrator(CalibrationError("the room was not quiet"))
    console = _console("keep\n")

    assert setup._automatic_floor(console, Config.defaults(), -45.0) == -45.0
    assert console.stderr.getvalue() == (
        "stenographer: automatic calibration rejected: the room was not quiet\n"
    )


def test_a_broken_capture_is_reported_as_failed_and_may_fall_back_to_manual(calibrator):
    calibrator(OSError("no such device"))
    console = _console("manual\n-70\n")

    assert setup._automatic_floor(console, Config.defaults(), -45.0) == -70.0
    assert console.stderr.getvalue() == (
        "stenographer: automatic calibration failed: no such device\n"
    )


def test_a_failed_capture_may_be_retried(calibrator):
    profile = (-59.0,) * 18
    calibrator(OSError("device busy"), profile)
    console = _console("retry\naccept\n")

    assert setup._automatic_floor(console, Config.defaults(), -45.0) == profile


def test_choose_floor_automatic_arm_runs_the_calibration(calibrator):
    profile = (-63.0,) * 18
    calibrator(profile)
    console = _console("automatic\naccept\n")

    assert setup._choose_floor(console, Config.defaults(), -45.0) == profile


@pytest.fixture
def binding_capture(monkeypatch):
    """Supply captured chords at the platform delegator, never opening a device."""

    from stenographer.cli.setup import binding_capture as capture_module

    def install(*results):
        pending = list(results)

        def capture(stdin, device, *, timeout):
            outcome = pending.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        monkeypatch.setattr(capture_module, "capture_binding", capture)

    return install


def test_a_captured_binding_is_offered_for_confirmation(binding_capture):
    binding_capture("KEY_LEFTCTRL+KEY_F9")
    console = _console("capture\ny\n")

    result = setup._capture_or_choose_binding(console, "KEY_RIGHTCTRL", None, new_config=True)

    assert result == "KEY_LEFTCTRL+KEY_F9"
    stdout = console.stdout.getvalue()
    assert "Press and release one key or a held chord now" in stdout
    assert "Captured binding: KEY_LEFTCTRL+KEY_F9" in stdout


def test_a_rejected_capture_can_be_retried(binding_capture):
    binding_capture("KEY_F9", "KEY_F10")
    console = _console("capture\nn\nretry\ny\n")

    result = setup._capture_or_choose_binding(console, "KEY_RIGHTCTRL", None, new_config=True)

    assert result == "KEY_F10"


def test_a_failed_capture_is_reported_and_may_be_typed_instead(
    binding_capture,
    key_vocabulary,
):
    from stenographer.lib.hotkey.errors import BindingCaptureError

    binding_capture(BindingCaptureError("no readable input device"))
    console = _console("capture\ntype\nKEY_F9\n")

    result = setup._capture_or_choose_binding(console, "KEY_RIGHTCTRL", None, new_config=True)

    assert result == "KEY_F9"
    assert console.stderr.getvalue() == (
        "stenographer: binding capture failed: no readable input device\n"
    )


def test_a_failed_capture_may_keep_the_current_binding(binding_capture):
    from stenographer.lib.hotkey.errors import BindingCaptureError

    binding_capture(BindingCaptureError("no readable input device"))
    console = _console("capture\nkeep\n")

    result = setup._capture_or_choose_binding(console, "KEY_RIGHTCTRL", None, new_config=True)

    assert result == "KEY_RIGHTCTRL"


def _caps(**overrides) -> Capabilities:
    state = {
        "key_injector_ok": True,
        "hotkey_access_ok": True,
        "has_mic": True,
        "model_cached": True,
        "clipboard_ok": True,
        "clipboard_backend": "wl-copy",
        "cue_player": "paplay",
        "service_enabled": "enabled",
        "service_active": "active",
    }
    state.update(overrides)
    return Capabilities(**state)


@pytest.fixture
def guided(monkeypatch):
    """Run ``_guided_setup`` with the cache, probe, report, and host all supplied."""

    from stenographer.cli.doctor import report as doctor
    from stenographer.cli.shared import capability_probe
    from stenographer.lib import platform as platform_module
    from stenographer.lib.diagnostics import capabilities as diagnostics
    from stenographer.lib.transcribe import download
    from stenographer.overlay import platform as overlay_platform_module

    events: list[str] = []

    def install(
        *,
        answers="",
        cached=True,
        cache_error=None,
        download_error=None,
        caps=None,
        probe_error=None,
        missing=(),
        restart=(True, ""),
        changed=True,
        custom_config=False,
        quick=False,
    ):
        probed = _caps() if caps is None else caps

        def is_model_cached(name):
            events.append(f"cache:{name}")
            if cache_error is not None:
                raise cache_error
            return cached

        def download_model(name):
            events.append(f"download:{name}")
            if download_error is not None:
                raise download_error

        def probe(cfg):
            events.append("probe")
            if probe_error is not None:
                raise probe_error
            return probed

        class Plat:
            def guidance(self):
                return _GUIDANCE

            def restart_service(self):
                events.append("restart")
                return restart

        class OverlayPlat:
            def guidance(self):
                return "overlay-guidance"

        monkeypatch.setattr(download, "is_model_cached", is_model_cached)
        monkeypatch.setattr(download, "download_model", download_model)
        monkeypatch.setattr(capability_probe, "probe", probe)
        monkeypatch.setattr(diagnostics, "missing_required", lambda caps: list(missing))
        monkeypatch.setattr(
            doctor,
            "render",
            lambda *args, **kwargs: "== doctor report ==",
        )
        monkeypatch.setattr(platform_module, "current_platform", Plat)
        monkeypatch.setattr(overlay_platform_module, "current_platform", OverlayPlat)

        console = _console(answers)
        code = setup._guided_setup(
            console,
            Config.defaults(),
            pathlib.Path("/cfg/config.toml"),
            changed=changed,
            custom_config=custom_config,
            quick=quick,
        )
        return code, console.stdout.getvalue(), console.stderr.getvalue(), events

    return install


def test_guided_setup_prints_the_doctor_report_and_succeeds(guided):
    code, stdout, stderr, events = guided(changed=False)

    assert code == 0
    assert "== doctor report ==" in stdout
    assert events == ["cache:dropbox-dash/faster-whisper-large-v3-turbo", "probe"]
    assert stderr == ""


def test_guided_setup_offers_the_download_of_an_uncached_model_and_takes_no_for_an_answer(guided):
    code, stdout, _, events = guided(cached=False, answers="\n", changed=False)

    assert code == 0
    assert "is not cached (download is approximately 1.6 GB)" in stdout
    assert "Download it from the network now? [y/N]: " in stdout
    assert "download:dropbox-dash/faster-whisper-large-v3-turbo" not in events


def test_guided_quick_setup_defaults_the_download_offer_to_yes(guided):
    code, stdout, _, events = guided(cached=False, answers="\n", changed=False, quick=True)

    assert code == 0
    assert "Download it from the network now? [Y/n]: " in stdout
    assert "download:dropbox-dash/faster-whisper-large-v3-turbo" in events
    assert "Model download complete." in stdout


def test_guided_setup_reports_a_failed_download_as_an_operational_failure(guided):
    code, stdout, stderr, _ = guided(
        cached=False,
        answers="y\n",
        download_error=OSError("no route to host"),
        changed=False,
    )

    assert code == 1
    assert stderr == "stenographer: model download failed: no route to host\n"
    assert "Model download complete." not in stdout


def test_guided_setup_reports_an_unreadable_model_cache_and_still_offers_the_download(guided):
    code, stdout, stderr, _ = guided(
        cache_error=OSError("cache permission denied"),
        answers="n\n",
        changed=False,
    )

    assert code == 1
    assert stderr == "stenographer: could not inspect the model cache: cache permission denied\n"
    assert "is not cached" in stdout


def test_guided_setup_stops_when_the_capability_probe_itself_fails(guided):
    code, stdout, stderr, _ = guided(probe_error=RuntimeError("probe exploded"))

    assert code == 1
    assert stderr == "stenographer: capability probe failed: probe exploded\n"
    assert "== doctor report ==" not in stdout


def test_guided_setup_withholds_the_restart_while_a_capability_is_missing(guided):
    code, stdout, _, events = guided(missing=("has_mic",))

    assert code == 78
    assert "Service restart skipped until required capabilities are available." in stdout
    assert "restart" not in events


def test_guided_setup_restarts_the_active_service_when_the_user_agrees(guided):
    code, stdout, _, events = guided(answers="\n")

    assert code == 0
    assert "Restart the active steno-agent to apply changes? [Y/n]: " in stdout
    assert "Restarted steno-agent." in stdout
    assert "restart" in events


def test_guided_setup_reports_a_failed_restart_as_an_operational_failure(guided):
    code, _, stderr, _ = guided(answers="\n", restart=(False, "unit not loaded"))

    assert code == 1
    assert stderr == "stenographer: could not restart steno-agent: unit not loaded\n"


def test_guided_quick_setup_closes_with_the_tryout_instructions(guided):
    code, stdout, _, events = guided(answers="n\n", quick=True)

    assert code == 0
    assert "restart" not in events
    assert "\nTry a real dictation" in stdout
    assert "Apply the saved configuration first with `steno-agent restart`." in stdout


def test_guided_setup_never_offers_a_restart_for_a_custom_config_path(guided):
    code, stdout, _, events = guided(custom_config=True)

    assert code == 0
    assert "Custom STENOGRAPHER_CONFIG path: service restart was not offered." in stdout
    assert "restart" not in events


def test_guided_setup_points_an_uninstalled_service_at_its_installer(guided):
    caps = _caps(service_enabled=None, service_active="inactive")

    code, stdout, _, _ = guided(caps=caps)

    assert code == 0
    assert "Service is not installed; run steno-agent install when ready." in stdout


def test_guided_setup_points_a_stopped_service_at_its_start_command(guided):
    caps = _caps(service_enabled="disabled", service_active="inactive")

    code, stdout, _, _ = guided(caps=caps)

    assert code == 0
    assert (
        "Service is not active; setup did not start it. Run `steno-agent start` when ready."
        in stdout
    )


def _document_double(tmp_path, *, save=None):
    from stenographer.lib.config.save_result import SaveResult

    path = tmp_path / "config.toml"

    class Document:
        def __init__(self):
            self.path = path
            self.config = Config.defaults()

        def save(self, config):
            if save is not None:
                return save(config)
            return SaveResult(True, path)

    return Document()


@pytest.fixture
def setup_run(monkeypatch, tmp_path):
    """Run ``setup`` past its terminal gate with the document and wizard supplied."""

    from stenographer.lib.logging import pipeline as logging_setup

    monkeypatch.setattr(setup, "require_interactive", lambda *args, **kwargs: None)
    monkeypatch.setattr(logging_setup, "apply_stderr_level", lambda level: None)

    def invoke(*, document=None, wizard=None, guided=None, quick=False):
        monkeypatch.setattr(
            setup,
            "load_document",
            lambda *args, **kwargs: _document_double(tmp_path) if document is None else document,
        )
        if wizard is not None:
            # ``run`` imports the quick wizard from its own module at call time,
            # so that is where the quick seam lives.
            from stenographer.cli.setup import quick as quick_module

            monkeypatch.setattr(setup, "_wizard", wizard)
            monkeypatch.setattr(quick_module, "_quick_wizard", wizard)
        if guided is not None:
            monkeypatch.setattr(setup, "_guided_setup", guided)
        stdout, stderr = io.StringIO(), io.StringIO()
        code = setup.run(quick=quick, stdin=io.StringIO(), stdout=stdout, stderr=stderr)
        return code, stdout.getvalue(), stderr.getvalue()

    return invoke


def test_a_cancelled_wizard_leaves_the_configuration_alone(setup_run, tmp_path):
    saved: list[Config] = []

    def refuse(*args, **kwargs):
        raise setup.SetupCancelledError

    code, stdout, _ = setup_run(
        document=_document_double(tmp_path, save=saved.append),
        wizard=refuse,
    )

    assert code == 0
    assert saved == []
    assert stdout.endswith("Setup cancelled; configuration was not changed.\n")


@pytest.mark.parametrize("failure", [KeyboardInterrupt, EOFError])
@pytest.mark.parametrize("quick", [False, True])
def test_an_interrupted_wizard_reports_the_interruption(setup_run, failure, quick):
    reached: list[bool] = []

    def interrupt(*args, **kwargs):
        reached.append(True)
        raise failure

    code, stdout, stderr = setup_run(wizard=interrupt, quick=quick)

    assert reached == [True]
    assert code == 130
    assert stderr == "stenographer: setup interrupted\n"
    assert stdout.endswith("\n\n")
    assert ("Stenographer quick setup" in stdout) is quick


def test_a_rejected_save_is_reported_and_fails(setup_run, tmp_path):
    from stenographer.lib.config.errors import ConfigError

    def refuse(config):
        raise ConfigError(tmp_path / "config.toml", "asr.model", "must be non-empty")

    code, _, stderr = setup_run(
        document=_document_double(tmp_path, save=refuse),
        wizard=lambda *args, **kwargs: Config.defaults(),
    )

    assert code == 1
    assert stderr.endswith("asr.model: must be non-empty\n")


def test_an_interrupted_save_reports_the_interruption(setup_run, tmp_path):
    def interrupt(config):
        raise KeyboardInterrupt

    code, _, stderr = setup_run(
        document=_document_double(tmp_path, save=interrupt),
        wizard=lambda *args, **kwargs: Config.defaults(),
    )

    assert code == 130
    assert stderr == "stenographer: setup interrupted\n"


@pytest.mark.parametrize("failure", [KeyboardInterrupt, EOFError])
def test_an_interruption_after_the_save_says_the_configuration_was_kept(setup_run, failure):
    def interrupt(*args, **kwargs):
        raise failure

    code, _, stderr = setup_run(
        wizard=lambda *args, **kwargs: Config.defaults(),
        guided=interrupt,
    )

    assert code == 130
    assert stderr == ("stenographer: setup interrupted; saved configuration was not rolled back\n")


def test_write_default_reports_an_unusable_target_and_fails(tmp_path, monkeypatch):
    # A regular file where the configuration directory belongs.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory\n", encoding="utf-8")
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(blocker / "config.toml"))
    out, err = io.StringIO(), io.StringIO()

    assert write_default(stdout=out, stderr=err) == 1

    assert out.getvalue() == ""
    # POSIX refuses the read through a non-directory; Windows reports the
    # target as absent and refuses creation of its parent instead.
    assert err.getvalue().startswith(
        ("stenographer: cannot re-read ", "stenographer: cannot create ")
    )
    assert str(blocker) in err.getvalue()
    assert blocker.read_text(encoding="utf-8") == "not a directory\n"


def test_refine_intro_says_where_the_transcript_would_go():
    local = setup.refine_intro_lines("http://127.0.0.1:11434", loopback=True)
    remote = setup.refine_intro_lines("http://192.168.1.5:11434", loopback=False)

    assert "http://127.0.0.1:11434 is on this machine, so nothing leaves it." in local
    assert not any("WARNING" in line for line in local)
    assert any("WARNING" in line and "leave this machine" in line for line in remote)
    assert any("reasoning is always disabled" in line for line in local)


@pytest.mark.parametrize(
    ("answer", "expected"),
    [("", "kept:tag"), ("2", "second:tag"), ("someone/custom:tag", "someone/custom:tag")],
)
def test_model_choice_keeps_selects_or_accepts_a_typed_tag(answer, expected):
    assert setup.parse_model_choice(answer, "kept:tag", ["first:tag", "second:tag"]) == expected


def test_a_number_outside_the_listing_is_taken_as_a_typed_tag():
    assert setup.parse_model_choice("9", "kept:tag", ["only:tag"]) == "9"


def test_the_refine_wizard_never_probes_ollama_while_the_stage_stays_off(monkeypatch):
    def forbidden(host):
        raise AssertionError("a disabled stage must not reach the network")

    monkeypatch.setattr(setup, "_refine_models", forbidden)
    console = _console("no\n")

    config = setup._edit_refine_section(console, Config.defaults(), ask_details=True)

    assert config.refine.enabled is False
    assert config.refine == Config.defaults().refine


def test_enabling_refine_lists_installed_models_and_takes_a_numbered_choice(monkeypatch):
    monkeypatch.setattr(setup, "_refine_models", lambda host: ["first:tag", "second:tag"])
    console = _console("yes\n\n2\n20\nyes\n")

    config = setup._edit_refine_section(console, Config.defaults(), ask_details=True)

    assert config.refine.enabled is True
    assert config.refine.model == "second:tag"
    assert config.refine.min_words == 20
    assert config.refine.structured_output is True
    assert "  1. first:tag" in console.stdout.getvalue()
    assert "Verified:" in console.stdout.getvalue()


def test_an_absent_ollama_still_lets_the_model_be_named_for_a_later_pull(monkeypatch):
    monkeypatch.setattr(setup, "_refine_models", lambda host: [])
    console = _console("yes\nsome/other:tag\n")

    config = setup._edit_refine_section(console, Config.defaults(), ask_details=False)

    assert config.refine.model == "some/other:tag"
    assert "No Ollama server answered" in console.stdout.getvalue()
    assert "model download --refine" in console.stdout.getvalue()


def test_the_model_hint_names_the_benchmarked_default_rather_than_a_literal():
    """A re-benchmark updates one constant; the wizard must follow it."""
    from stenographer.lib.refine.prompt import DEFAULT_MODEL

    hint = setup.refine_model_hint()

    assert DEFAULT_MODEL in hint
    assert "qwen3.5:4b" in hint and "structured_output" in hint
    assert "unverified" in hint
