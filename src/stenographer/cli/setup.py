# SPDX-License-Identifier: GPL-3.0-or-later
"""Interactive configuration review and guided machine setup.

The prompt and policy helpers are pure. Hardware, network, and systemd work is
kept in the command path and is imported only after CLI dispatch.
"""

from __future__ import annotations

import dataclasses
import functools
import pathlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, TextIO

from stenographer.cli.console import (
    Console,
    ask_yes_no,
    custom_config_selected,
    load_document,
    open_console,
    parse_bool,
    report_save,
    require_interactive,
    restart_service,
)
from stenographer.cli.setup_config import ConfigPersistenceError
from stenographer.config import ALLOWED_COMPUTE_TYPES, Config, ConfigError

if TYPE_CHECKING:
    from stenographer.platform.base import HostGuidance

_CLEAR = "clear"
_SECTIONS = ("hotkey", "audio", "asr", "feedback")
#: The keys the quick wizard edits, in the order its review screen lists them.
_QUICK_REVIEW_FIELDS = (
    ("hotkey", "device"),
    ("hotkey", "binding"),
    ("hotkey", "mode"),
    ("audio", "input_device"),
    ("feedback", "volume"),
    ("feedback", "mute"),
    ("feedback", "overlay"),
    ("feedback", "sound_pack"),
    ("feedback", "spectrum_floor_dbfs"),
)


class SetupCancelledError(Exception):
    """Normal cancellation from the final review screen."""


def parse_optional_string(text: str, current: str | None) -> str | None:
    """Empty retains *current*; the explicit ``clear`` token unsets it."""

    value = text.strip()
    if not value:
        return current
    if value.casefold() == _CLEAR:
        return None
    return value


def parse_choice(text: str, current: str, choices: Iterable[str]) -> str:
    """Parse a case-insensitive choice, retaining the current value on Enter."""

    allowed = tuple(choices)
    value = text.strip().casefold()
    if not value:
        return current
    matches = [choice for choice in allowed if choice.casefold() == value]
    if not matches:
        raise ValueError(f"choose one of: {', '.join(allowed)}")
    return matches[0]


def parse_number(
    text: str,
    current: int | float,
    *,
    minimum: int | float,
    maximum: int | float,
    integer: bool = False,
) -> int | float:
    """Parse a bounded number, retaining the current value on Enter."""

    value = text.strip()
    if not value:
        return current
    try:
        parsed: int | float = int(value) if integer else float(value)
    except ValueError as exc:
        kind = "integer" if integer else "number"
        raise ValueError(f"enter a {kind} in [{minimum}, {maximum}]") from exc
    if not minimum <= parsed <= maximum:
        raise ValueError(f"must be in [{minimum}, {maximum}]")
    return parsed


def parse_review_action(text: str) -> str:
    """Return ``save``, ``cancel``, or a section name from a review response."""

    value = text.strip().casefold()
    actions = {
        "": "save",
        "s": "save",
        "save": "save",
        "c": "cancel",
        "cancel": "cancel",
        "1": "hotkey",
        "h": "hotkey",
        "hotkey": "hotkey",
        "2": "audio",
        "a": "audio",
        "audio": "audio",
        "3": "asr",
        "asr": "asr",
        "4": "feedback",
        "f": "feedback",
        "feedback": "feedback",
    }
    try:
        return actions[value]
    except KeyError:
        raise ValueError("choose Save, Cancel, or section 1-4") from None


def parse_quick_review_action(text: str) -> str:
    """Return ``save`` or ``cancel`` from a quick-review response."""

    value = text.strip().casefold()
    if value in {"", "s", "save"}:
        return "save"
    if value in {"c", "cancel"}:
        return "cancel"
    raise ValueError("choose Save or Cancel")


def restart_eligible(
    *,
    config_changed: bool,
    custom_config: bool,
    missing_required: bool,
    service_active: str | None,
) -> bool:
    """Whether setup may offer a service restart."""

    return (
        config_changed and not custom_config and not missing_required and service_active == "active"
    )


def followup_exit_code(*, operational_failure: bool, missing_required: bool) -> int:
    """Operational failures take precedence over a doctor capability failure."""

    if operational_failure:
        return 1
    if missing_required:
        return 78
    return 0


def _display_optional(value: object) -> str:
    return "automatic/unset" if value is None else str(value)


def field_display(value: object, field_name: str) -> str:
    """Render one configuration value the way both review screens show it."""

    if field_name == "spectrum_floor_dbfs" and isinstance(value, tuple):
        return "calibrated 18-band profile"
    return _display_optional(value)


def review_lines(config: Config) -> list[str]:
    """Render the full review: every section, every field, in declaration order."""

    lines = ["\nReview"]
    for section_name in _SECTIONS:
        lines.append(f"[{section_name}]")
        section = getattr(config, section_name)
        for field in dataclasses.fields(section):
            value = field_display(getattr(section, field.name), field.name)
            lines.append(f"  {field.name} = {value}")
    return lines


def quick_review_lines(config: Config) -> list[str]:
    """Render the quick review: only the keys the quick wizard can change."""

    lines = ["\nQuick setup review"]
    for section_name, field_name in _QUICK_REVIEW_FIELDS:
        value = getattr(getattr(config, section_name), field_name)
        lines.append(f"  {section_name}.{field_name} = {field_display(value, field_name)}")
    lines.append("Audio-gate, recording-limit, and all ASR settings will be retained unchanged.")
    return lines


def quick_tryout_lines(
    config: Config,
    path: pathlib.PurePath,
    guidance: HostGuidance,
    *,
    custom_config: bool,
    service_enabled: str | None,
    service_active: str | None,
    restart_pending: bool,
) -> list[str]:
    """Render the closing tryout instructions for a successful quick setup.

    Which daemon the user should reach for depends on the config path, whether a
    restart is still pending, and the service state; the trigger sentence
    depends on the hotkey mode, and the log hint on the config path again.
    """

    lines = ["\nTry a real dictation"]
    if custom_config:
        command = guidance.run_with_config(str(path))
        lines.append(f"Run `{command}` in a terminal; the standard service was not changed.")
    elif restart_pending:
        lines.append(
            f"Apply the saved configuration first with `{guidance.service_restart_command}`."
        )
    elif service_active == "active":
        lines.append(f"{guidance.service_name} is active and ready for a tryout.")
    elif service_enabled is None and service_active == "inactive":
        lines.append(
            "The service is not installed. Run `stenographer run` in a terminal, "
            f"or install it with `{guidance.service_installer}`."
        )
    elif service_active is not None:
        lines.append(
            "The service is inactive. Start it with "
            f"`{guidance.service_start_command}`; setup did not start it."
        )
    else:
        lines.append(
            "The user-service state could not be determined. Run `stenographer run` "
            "in a terminal to try the configuration."
        )

    if config.hotkey.mode == "toggle":
        lines.append(
            f"Focus a text field, press {config.hotkey.binding}, speak, then press it again."
        )
    else:
        lines.append(f"Focus a text field, hold {config.hotkey.binding}, speak, then release it.")
    if custom_config:
        lines.append(
            "Watch that foreground command for logs; the standard service log is "
            f"`{guidance.service_log_command}`."
        )
    else:
        lines.append(f"Follow service logs with `{guidance.service_log_command}`.")
    return lines


def _prompt_string(console: Console, label: str, current: str) -> str:
    def parse(text: str) -> str:
        return text.strip() or current

    return str(console.validated(f"{label} [{current}]: ", parse))


def _prompt_optional(console: Console, label: str, current: str | None) -> str | None:
    prompt = f"{label} [{_display_optional(current)}; Enter keeps, '{_CLEAR}' unsets]: "
    return console.validated(prompt, lambda text: parse_optional_string(text, current))


def _prompt_choice(console: Console, label: str, current: str, choices: Sequence[str]) -> str:
    joined = "/".join(choices)
    prompt = f"{label} ({joined}) [{current}]: "
    return str(console.validated(prompt, lambda text: parse_choice(text, current, choices)))


def _prompt_bool(console: Console, label: str, current: bool) -> bool:
    default = "yes" if current else "no"
    return bool(
        console.validated(f"{label} (yes/no) [{default}]: ", lambda s: parse_bool(s, current))
    )


def _prompt_number(
    console: Console,
    label: str,
    current: int | float,
    minimum: int | float,
    maximum: int | float,
    *,
    integer: bool = False,
) -> int | float:
    prompt = f"{label} [{current}; {minimum}..{maximum}]: "
    return console.validated(
        prompt,
        lambda text: parse_number(text, current, minimum=minimum, maximum=maximum, integer=integer),
    )


def _prompt_sound_pack(console: Console, current: str, config_dir: pathlib.Path) -> str:
    """Offer bundled and valid custom packs without playing any cue."""

    from stenographer.cli.sounds import parse_sound_pack_choice
    from stenographer.delivery.feedback import discover_sound_packs

    choices = discover_sound_packs(config_dir)
    console.write("Sound packs:")
    for number, name in enumerate(choices, 1):
        console.write(f"  {number}. {name}")
    prompt = f"Sound pack [{current}; Enter keeps, number/name selects]: "
    return str(
        console.validated(
            prompt,
            lambda text: parse_sound_pack_choice(text, current, choices),
        )
    )


def _audio_devices() -> list[tuple[str, str]]:
    """Return selectable input devices. An unusable PortAudio means no suggestions."""

    from stenographer.audio_probe import input_device_choices, query_devices

    return input_device_choices(query_devices().devices)


def _hotkey_devices() -> list[tuple[str, str]]:
    """Return the platform's selectable hotkey devices as ``(value, label)`` pairs."""
    from stenographer.platform import current_platform

    return current_platform().hotkey_devices()


def _prompt_device(
    console: Console,
    label: str,
    current: str | None,
    devices: Sequence[tuple[str, str]],
) -> str | None:
    console.write(f"{label} devices (automatic selection is always available):")
    if devices:
        for number, (_, description) in enumerate(devices, 1):
            console.write(f"  {number}. {description}")
    else:
        console.write("  (no selectable devices found; manual entry is still available)")

    def parse(text: str) -> str | None:
        value = text.strip()
        if not value:
            return current
        if value.casefold() in {_CLEAR, "auto", "automatic"}:
            return None
        if value.isdecimal() and 1 <= int(value) <= len(devices):
            return devices[int(value) - 1][0]
        return value

    prompt = (
        f"{label} [{_display_optional(current)}; Enter keeps, number selects, "
        "'auto' unsets, or type a value]: "
    )
    return console.validated(prompt, parse)


def _parse_binding(text: str) -> str:
    value = text.strip()
    if not value:
        raise ValueError("binding must be non-empty")
    from stenographer.hotkey import BindingError, parse_binding
    from stenographer.platform import current_platform

    try:
        parse_binding(value, current_platform().keys())
    except BindingError as exc:
        raise ValueError(str(exc)) from exc
    return value


def _prompt_typed_binding(console: Console, current: str) -> str:
    return str(
        console.validated(
            f"Binding [{current}]: ",
            lambda text: _parse_binding(text.strip() or current),
        )
    )


def _edit_hotkey(console: Console, config: Config) -> Config:
    console.write("\nHotkey")
    console.write(
        "Binding uses key names (the evdev KEY_* vocabulary) joined with '+'. "
        "Mode is hold or toggle only."
    )

    hotkey = dataclasses.replace(
        config.hotkey,
        binding=_prompt_typed_binding(console, config.hotkey.binding),
    )
    hotkey = dataclasses.replace(
        hotkey,
        device=_prompt_device(console, "Hotkey", hotkey.device, _hotkey_devices()),
        mode=_prompt_choice(console, "Trigger mode", hotkey.mode, ("hold", "toggle")),
    )
    return dataclasses.replace(config, hotkey=hotkey)


def _edit_audio(console: Console, config: Config) -> Config:
    console.write("\nAudio")
    console.write("min_speech_rms is the pre-decode energy gate; 0 disables it.")
    audio = dataclasses.replace(
        config.audio,
        input_device=_prompt_device(
            console, "Audio input", config.audio.input_device, _audio_devices()
        ),
    )
    audio = dataclasses.replace(
        audio,
        min_speech_rms=float(
            _prompt_number(console, "Minimum speech RMS", audio.min_speech_rms, 0.0, 1.0)
        ),
        max_recording_seconds=int(
            _prompt_number(
                console,
                "Maximum recording seconds",
                audio.max_recording_seconds,
                1,
                86400,
                integer=True,
            )
        ),
    )
    return dataclasses.replace(config, audio=audio)


def _edit_asr(console: Console, config: Config) -> Config:
    console.write("\nASR")
    asr = dataclasses.replace(
        config.asr,
        model=_prompt_string(console, "Model", config.asr.model),
        compute_type=_prompt_choice(
            console, "Compute type", config.asr.compute_type, tuple(sorted(ALLOWED_COMPUTE_TYPES))
        ),
        beam_size=int(
            _prompt_number(console, "Beam size", config.asr.beam_size, 1, 10, integer=True)
        ),
        hotwords=_prompt_optional(console, "Hotwords", config.asr.hotwords),
        initial_prompt=_prompt_optional(console, "Initial prompt", config.asr.initial_prompt),
        vad_filter=_prompt_bool(console, "VAD filter", config.asr.vad_filter),
        silence_threshold=float(
            _prompt_number(console, "Silence threshold", config.asr.silence_threshold, 0.0, 1.0)
        ),
        idle_unload_seconds=int(
            _prompt_number(
                console,
                "Idle unload seconds",
                config.asr.idle_unload_seconds,
                0,
                86400,
                integer=True,
            )
        ),
        cpu_threads=int(
            _prompt_number(
                console, "CPU threads (0 = auto)", config.asr.cpu_threads, 0, 64, integer=True
            )
        ),
    )
    return dataclasses.replace(config, asr=asr)


def _manual_floor(console: Console, current: float | tuple[float, ...]) -> float:
    from stenographer.overlay.spectrum import DEFAULT_SPECTRUM_FLOOR_DBFS

    scalar = current if isinstance(current, float) else DEFAULT_SPECTRUM_FLOOR_DBFS
    return float(_prompt_number(console, "Spectrum floor dBFS", scalar, -96.0, -13.0))


def _automatic_floor(
    console: Console,
    config: Config,
    current: float | tuple[float, ...],
) -> float | tuple[float, ...]:
    from stenographer.cli.calibration import CalibrationError, calibrate_spectrum_profile

    while True:
        console.write("Keep the room quiet. Calibration prepares the selected microphone first.")
        try:
            estimate = calibrate_spectrum_profile(
                config.audio.input_device,
                on_countdown=lambda remaining: console.write(
                    "Recording room noise now."
                    if remaining == 0
                    else f"Stay silent — recording starts in {remaining}..."
                ),
                on_voice_prompt=lambda: console.write(
                    "Speak normally now for three seconds so visibility can be verified."
                ),
            )
        except Exception as exc:
            # A CalibrationError is the estimator refusing the capture; anything
            # else is the machine failing to produce one.
            outcome = "rejected" if isinstance(exc, CalibrationError) else "failed"
            console.error(f"automatic calibration {outcome}: {exc}")
            action = _prompt_choice(console, "Next", "keep", ("retry", "manual", "keep"))
            if action == "retry":
                continue
            if action == "manual":
                return _manual_floor(console, current)
            return current

        console.write("Background profile learned and normal voice visibility verified.")
        action = _prompt_choice(console, "Result", "accept", ("accept", "retry", "manual", "keep"))
        if action == "accept":
            return estimate
        if action == "retry":
            continue
        if action == "manual":
            return _manual_floor(console, current)
        return current


def _choose_floor(
    console: Console,
    config: Config,
    current: float | tuple[float, ...],
) -> float | tuple[float, ...]:
    """Offer the automatic / keep / manual spectrum-response choice and apply it."""

    default_action = "keep" if isinstance(current, tuple) else "automatic"
    action = _prompt_choice(
        console,
        "Spectrum response",
        default_action,
        ("automatic", "keep", "manual"),
    )
    if action == "manual":
        return _manual_floor(console, current)
    if action == "automatic":
        return _automatic_floor(console, config, current)
    return current


def _edit_feedback_section(
    console: Console,
    config: Config,
    config_dir: pathlib.Path,
    *,
    notice: Sequence[str],
    skip_floor_without_overlay: bool,
) -> Config:
    """Prompt the feedback keys both wizards share, then the spectrum response.

    The wizards differ only in *notice* (their calibration disclaimer) and in
    whether a disabled overlay skips the spectrum question entirely.
    """

    console.write("\nFeedback")
    feedback = dataclasses.replace(
        config.feedback,
        volume=float(_prompt_number(console, "Cue volume", config.feedback.volume, 0.0, 1.0)),
        mute=_prompt_bool(console, "Mute cues", config.feedback.mute),
        overlay=_prompt_bool(console, "Show lifecycle overlay", config.feedback.overlay),
        sound_pack=_prompt_sound_pack(console, config.feedback.sound_pack, config_dir),
    )
    console.write()
    for line in notice:
        console.write(line)
    floor = feedback.spectrum_floor_dbfs
    if skip_floor_without_overlay and not feedback.overlay:
        console.write("Overlay is disabled, so display-spectrum calibration was skipped.")
    else:
        # Calibration only reads the (already chosen) input device from here.
        floor = _choose_floor(console, dataclasses.replace(config, feedback=feedback), floor)
    return dataclasses.replace(
        config,
        feedback=dataclasses.replace(feedback, spectrum_floor_dbfs=floor),
    )


def _edit_feedback(console: Console, config: Config, *, config_dir: pathlib.Path) -> Config:
    return _edit_feedback_section(
        console,
        config,
        config_dir,
        notice=(
            "IMPORTANT: spectrum calibration affects only the 18 visual bars.",
            "It never changes capture, min_speech_rms, speech gating, or transcription.",
        ),
        skip_floor_without_overlay=False,
    )


def _editors(config_dir: pathlib.Path) -> Mapping[str, Callable[[Console, Config], Config]]:
    """Bind the section editors to *config_dir*; only feedback has any use for it."""

    return {
        "hotkey": _edit_hotkey,
        "audio": _edit_audio,
        "asr": _edit_asr,
        "feedback": functools.partial(_edit_feedback, config_dir=config_dir),
    }


def _review(console: Console, config: Config) -> None:
    for line in review_lines(config):
        console.write(line)


def _wizard(console: Console, initial: Config, config_dir: pathlib.Path) -> Config:
    editors = _editors(config_dir)
    config = initial
    for section in _SECTIONS:
        config = editors[section](console, config)
    while True:
        _review(console, config)
        action = console.validated(
            "Save [Enter/S], Cancel [C], or re-edit 1 Hotkey / 2 Audio / 3 ASR / 4 Feedback: ",
            parse_review_action,
        )
        if action == "save":
            return config
        if action == "cancel":
            raise SetupCancelledError
        config = editors[str(action)](console, config)


def _capture_or_choose_binding(
    console: Console,
    current: str,
    device: str | None,
    *,
    new_config: bool,
) -> str:
    default = "capture" if new_config else "keep"
    action = _prompt_choice(console, "Binding", default, ("capture", "keep", "type"))
    if action == "keep":
        return current
    if action == "type":
        return _prompt_typed_binding(console, current)

    from stenographer.binding_capture import BindingCaptureError
    from stenographer.cli.binding_capture import capture_binding

    while True:
        console.write(
            "Press and release one key or a held chord now (15-second timeout; Ctrl-C cancels)."
        )
        try:
            captured = capture_binding(console.stdin, device, timeout=15.0)
        except BindingCaptureError as exc:
            console.error(f"binding capture failed: {exc}")
        else:
            console.write(f"Captured binding: {captured}")
            if ask_yes_no(console, "Use this binding?", default=True):
                return captured

        action = _prompt_choice(console, "Next", "retry", ("retry", "type", "keep"))
        if action == "retry":
            continue
        if action == "type":
            return _prompt_typed_binding(console, current)
        return current


def _quick_wizard(
    console: Console,
    initial: Config,
    config_dir: pathlib.Path,
    *,
    new_config: bool,
) -> Config:
    config = initial
    console.write("\nHotkey")
    device = _prompt_device(console, "Hotkey", config.hotkey.device, _hotkey_devices())
    binding = _capture_or_choose_binding(
        console,
        config.hotkey.binding,
        device,
        new_config=new_config,
    )
    mode = _prompt_choice(console, "Trigger mode", config.hotkey.mode, ("hold", "toggle"))
    config = dataclasses.replace(
        config,
        hotkey=dataclasses.replace(config.hotkey, device=device, binding=binding, mode=mode),
    )

    console.write("\nMicrophone")
    input_device = _prompt_device(
        console,
        "Audio input",
        config.audio.input_device,
        _audio_devices(),
    )
    config = dataclasses.replace(
        config,
        audio=dataclasses.replace(config.audio, input_device=input_device),
    )

    config = _edit_feedback_section(
        console,
        config,
        config_dir,
        notice=(
            "IMPORTANT: spectrum calibration controls only the 18 display bars.",
            "It does not affect capture, speech detection, audio gates, ASR, or transcription.",
        ),
        skip_floor_without_overlay=True,
    )

    for line in quick_review_lines(config):
        console.write(line)
    action = console.validated("Save [Enter/S] or Cancel [C]: ", parse_quick_review_action)
    if action == "cancel":
        raise SetupCancelledError
    return config


def _guided_setup(
    console: Console,
    config: Config,
    path: pathlib.Path,
    *,
    changed: bool,
    custom_config: bool,
    quick: bool = False,
) -> int:
    from stenographer import capabilities
    from stenographer.cli import doctor
    from stenographer.platform import current_platform
    from stenographer.transcribe import model

    guidance = current_platform().guidance()
    operational_failure = False
    try:
        cached = model.is_model_cached(config.asr.model)
    except Exception as exc:
        console.error(f"could not inspect the model cache: {exc}")
        cached = False
        operational_failure = True
    if not cached:
        console.write(
            f"\nModel {config.asr.model} is not cached (download is approximately 1.5 GB)."
        )
        if ask_yes_no(console, "Download it from the network now?", default=quick):
            try:
                model.download_model(config.asr.model)
            except Exception as exc:
                console.error(f"model download failed: {exc}")
                operational_failure = True
            else:
                console.write("Model download complete.")

    try:
        caps = capabilities.probe(config)
    except Exception as exc:
        console.error(f"capability probe failed: {exc}")
        return 1
    console.write()
    console.write(doctor.render(caps, config, path, guidance))
    missing = bool(capabilities.missing_required(caps))
    if missing:
        console.write("Service restart skipped until required capabilities are available.")
        return followup_exit_code(operational_failure=operational_failure, missing_required=True)

    restart_pending = False
    if restart_eligible(
        config_changed=changed,
        custom_config=custom_config,
        missing_required=False,
        service_active=caps.service_active,
    ):
        if ask_yes_no(
            console,
            f"Restart the active {guidance.service_name} to apply changes?",
            default=True,
        ):
            if not restart_service(console):
                operational_failure = True
        else:
            restart_pending = True
    elif changed and custom_config:
        console.write("Custom STENOGRAPHER_CONFIG path: service restart was not offered.")
    elif changed and caps.service_active != "active":
        if caps.service_enabled is None:
            console.write(f"Service is not installed; run {guidance.service_installer} when ready.")
        else:
            console.write(
                "Service is not active; setup did not start it. "
                f"Run `{guidance.service_start_command}` when ready."
            )
    exit_code = followup_exit_code(
        operational_failure=operational_failure,
        missing_required=False,
    )
    if quick and exit_code == 0:
        _print_quick_tryout(
            console,
            config,
            path,
            guidance,
            custom_config=custom_config,
            service_enabled=caps.service_enabled,
            service_active=caps.service_active,
            restart_pending=restart_pending,
        )
    return exit_code


def _print_quick_tryout(
    console: Console,
    config: Config,
    path: pathlib.Path,
    guidance: HostGuidance,
    *,
    custom_config: bool,
    service_enabled: str | None,
    service_active: str | None,
    restart_pending: bool,
) -> None:
    for line in quick_tryout_lines(
        config,
        path,
        guidance,
        custom_config=custom_config,
        service_enabled=service_enabled,
        service_active=service_active,
        restart_pending=restart_pending,
    ):
        console.write(line)


def run(
    *,
    quick: bool = False,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run the TTY-only setup wizard and guided capability checks."""

    console = open_console(stdin, stdout, stderr)
    gate = require_interactive(console, "setup requires an interactive terminal")
    if gate is not None:
        return gate

    custom_config = custom_config_selected()
    loaded = load_document(
        console,
        interrupt_message="setup interrupted",
        blank_line_before_interrupt=True,
    )
    if isinstance(loaded, int):
        return loaded
    document = loaded
    path = document.path

    console.write("Stenographer quick setup" if quick else "Stenographer setup")
    console.write(f"Configuration: {path}")
    console.write("Press Enter to retain each current value.")
    try:
        reviewed = (
            _quick_wizard(console, document.config, path.parent, new_config=not path.exists())
            if quick
            else _wizard(console, document.config, path.parent)
        )
    except SetupCancelledError:
        console.write("Setup cancelled; configuration was not changed.")
        return 0
    except (KeyboardInterrupt, EOFError):
        console.write()
        console.error("setup interrupted")
        return 130

    try:
        result = document.save(reviewed)
    except ConfigPersistenceError as exc:
        console.error(str(exc))
        return 1
    except ConfigError as exc:
        console.error(str(exc))
        return 1
    except KeyboardInterrupt:
        console.write()
        console.error("setup interrupted")
        return 130
    report_save(
        console,
        result,
        saved_prefix="Saved",
        unchanged_message="Configuration is unchanged; no file was written.",
    )

    try:
        return _guided_setup(
            console,
            reviewed,
            path,
            changed=result.changed,
            custom_config=custom_config,
            quick=quick,
        )
    except (KeyboardInterrupt, EOFError):
        console.write()
        console.error("setup interrupted; saved configuration was not rolled back")
        return 130
