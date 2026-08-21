# SPDX-License-Identifier: GPL-3.0-or-later
"""Interactive configuration review and guided machine setup.

The prompt and policy helpers are pure. Hardware, network, and systemd work is
kept in the command path and is imported only after CLI dispatch.
"""

from __future__ import annotations

import contextlib
import dataclasses
import os
import pathlib
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import TextIO

from stenographer.cli.setup_config import ConfigDocument, ConfigPersistenceError
from stenographer.config import ALLOWED_COMPUTE_TYPES, Config, ConfigError

_CLEAR = "clear"
_SECTIONS = ("hotkey", "audio", "asr", "feedback")


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


def parse_bool(text: str, current: bool) -> bool:
    """Parse yes/no with Enter retaining the current value."""

    value = text.strip().casefold()
    if not value:
        return current
    if value in {"y", "yes", "true", "on", "1"}:
        return True
    if value in {"n", "no", "false", "off", "0"}:
        return False
    raise ValueError("enter yes or no")


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


@dataclasses.dataclass
class _Console:
    stdin: TextIO
    stdout: TextIO
    stderr: TextIO

    def write(self, message: str = "") -> None:
        print(message, file=self.stdout)

    def error(self, message: str) -> None:
        print(f"stenographer: {message}", file=self.stderr)

    def ask(self, prompt: str) -> str:
        self.stdout.write(prompt)
        self.stdout.flush()
        line = self.stdin.readline()
        if line == "":
            raise EOFError
        return line.rstrip("\r\n")

    def validated(self, prompt: str, parser: Callable[[str], object]) -> object:
        while True:
            try:
                return parser(self.ask(prompt))
            except ValueError as exc:
                self.error(str(exc))


def _display_optional(value: str | None) -> str:
    return value if value is not None else "automatic/unset"


def _prompt_string(console: _Console, label: str, current: str) -> str:
    def parse(text: str) -> str:
        return text.strip() or current

    return str(console.validated(f"{label} [{current}]: ", parse))


def _prompt_optional(console: _Console, label: str, current: str | None) -> str | None:
    prompt = f"{label} [{_display_optional(current)}; Enter keeps, '{_CLEAR}' unsets]: "
    return console.validated(prompt, lambda text: parse_optional_string(text, current))  # type: ignore[return-value]


def _prompt_choice(console: _Console, label: str, current: str, choices: Sequence[str]) -> str:
    joined = "/".join(choices)
    prompt = f"{label} ({joined}) [{current}]: "
    return str(console.validated(prompt, lambda text: parse_choice(text, current, choices)))


def _prompt_bool(console: _Console, label: str, current: bool) -> bool:
    default = "yes" if current else "no"
    return bool(
        console.validated(f"{label} (yes/no) [{default}]: ", lambda s: parse_bool(s, current))
    )


def _prompt_number(
    console: _Console,
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
    )  # type: ignore[return-value]


def _audio_devices() -> list[tuple[str, str]]:
    """Return selectable input devices. PortAudio errors degrade to no suggestions."""

    try:
        import sounddevice
    except ImportError:
        return []

    try:
        devices = sounddevice.query_devices()
    except Exception:
        return []
    return [
        (str(index), f"{index}: {device.get('name', '?')}")
        for index, device in enumerate(devices)
        if device.get("max_input_channels", 0) > 0
    ]


def _hotkey_devices() -> list[tuple[str, str]]:
    """Return readable evdev devices with key capabilities."""

    try:
        import evdev
    except ImportError:
        return []

    devices: list[tuple[str, str]] = []
    try:
        paths = evdev.list_devices()
    except OSError:
        return devices
    for path in paths:
        try:
            device = evdev.InputDevice(path)
        except OSError:
            continue
        try:
            try:
                has_keys = evdev.ecodes.EV_KEY in device.capabilities()
            except OSError:
                continue
            if has_keys:
                devices.append((path, f"{path}: {device.name}"))
        finally:
            with contextlib.suppress(OSError):
                device.close()
    return devices


def _prompt_device(
    console: _Console,
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
    return console.validated(prompt, parse)  # type: ignore[return-value]


def _edit_hotkey(console: _Console, config: Config) -> Config:
    console.write("\nHotkey")
    console.write("Binding uses evdev key names joined with '+'. Mode is hold or toggle only.")

    def binding(text: str) -> str:
        value = text.strip() or config.hotkey.binding
        if not value:
            raise ValueError("binding must be non-empty")
        from stenographer.hotkey import BindingError, parse_binding

        try:
            parse_binding(value)
        except BindingError as exc:
            raise ValueError(str(exc)) from exc
        return value

    hotkey = dataclasses.replace(
        config.hotkey,
        binding=str(console.validated(f"Binding [{config.hotkey.binding}]: ", binding)),
    )
    hotkey = dataclasses.replace(
        hotkey,
        device=_prompt_device(console, "Hotkey", hotkey.device, _hotkey_devices()),
        mode=_prompt_choice(console, "Trigger mode", hotkey.mode, ("hold", "toggle")),
    )
    return dataclasses.replace(config, hotkey=hotkey)


def _edit_audio(console: _Console, config: Config) -> Config:
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


def _edit_asr(console: _Console, config: Config) -> Config:
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


def _manual_floor(console: _Console, current: float) -> float:
    return float(_prompt_number(console, "Spectrum floor dBFS", current, -96.0, -13.0))


def _automatic_floor(console: _Console, config: Config, current: float) -> float:
    from stenographer.cli.calibration import CalibrationError, calibrate_spectrum_floor

    while True:
        console.write("Keep the room quiet. Calibration prepares the selected microphone first.")
        try:
            estimate = calibrate_spectrum_floor(
                config.audio.input_device,
                on_countdown=lambda remaining: console.write(
                    "Recording room noise now."
                    if remaining == 0
                    else f"Stay silent — recording starts in {remaining}..."
                ),
            )
        except CalibrationError as exc:
            console.error(f"automatic calibration rejected: {exc}")
            action = _prompt_choice(console, "Next", "keep", ("retry", "manual", "keep"))
            if action == "retry":
                continue
            if action == "manual":
                return _manual_floor(console, current)
            return current
        except Exception as exc:
            console.error(f"automatic calibration failed: {exc}")
            action = _prompt_choice(console, "Next", "keep", ("retry", "manual", "keep"))
            if action == "retry":
                continue
            if action == "manual":
                return _manual_floor(console, current)
            return current

        console.write(f"Suggested display spectrum floor: {estimate:.0f} dBFS")
        action = _prompt_choice(console, "Result", "accept", ("accept", "retry", "manual", "keep"))
        if action == "accept":
            return estimate
        if action == "retry":
            continue
        if action == "manual":
            return _manual_floor(console, current)
        return current


def _edit_feedback(console: _Console, config: Config) -> Config:
    console.write("\nFeedback")
    feedback = dataclasses.replace(
        config.feedback,
        volume=float(_prompt_number(console, "Cue volume", config.feedback.volume, 0.0, 1.0)),
        mute=_prompt_bool(console, "Mute cues", config.feedback.mute),
        overlay=_prompt_bool(console, "Show lifecycle overlay", config.feedback.overlay),
    )
    console.write()
    console.write("IMPORTANT: spectrum calibration affects only the 18 visual bars.")
    console.write("It never changes capture, min_speech_rms, speech gating, or transcription.")
    action = _prompt_choice(console, "Spectrum floor", "keep", ("keep", "manual", "automatic"))
    floor = feedback.spectrum_floor_dbfs
    if action == "manual":
        floor = _manual_floor(console, floor)
    elif action == "automatic":
        floor = _automatic_floor(console, config, floor)
    feedback = dataclasses.replace(feedback, spectrum_floor_dbfs=floor)
    return dataclasses.replace(config, feedback=feedback)


_EDITORS: Mapping[str, Callable[[_Console, Config], Config]] = {
    "hotkey": _edit_hotkey,
    "audio": _edit_audio,
    "asr": _edit_asr,
    "feedback": _edit_feedback,
}


def _review(console: _Console, config: Config) -> None:
    console.write("\nReview")
    for section_name in _SECTIONS:
        console.write(f"[{section_name}]")
        section = getattr(config, section_name)
        for field in dataclasses.fields(section):
            value = getattr(section, field.name)
            console.write(
                f"  {field.name} = {_display_optional(value) if value is None else value}"
            )


def _wizard(console: _Console, initial: Config) -> Config:
    config = initial
    for section in _SECTIONS:
        config = _EDITORS[section](console, config)
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
        config = _EDITORS[str(action)](console, config)


def _ask_yes_no(console: _Console, prompt: str, *, default: bool) -> bool:
    marker = "Y/n" if default else "y/N"
    return bool(console.validated(f"{prompt} [{marker}]: ", lambda text: parse_bool(text, default)))


def _restart_service(console: _Console) -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "--user", "restart", "stenographer.service"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        console.error(f"could not restart stenographer.service: {exc}")
        return False
    if result.returncode != 0:
        detail = result.stderr.strip() or f"systemctl exited {result.returncode}"
        console.error(f"could not restart stenographer.service: {detail}")
        return False
    console.write("Restarted stenographer.service.")
    return True


def _guided_setup(
    console: _Console,
    config: Config,
    path: pathlib.Path,
    *,
    changed: bool,
    custom_config: bool,
) -> int:
    from stenographer.cli import doctor
    from stenographer.transcribe import model

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
        if _ask_yes_no(console, "Download it from the network now?", default=False):
            try:
                model.download_model(config.asr.model)
            except Exception as exc:
                console.error(f"model download failed: {exc}")
                operational_failure = True
            else:
                console.write("Model download complete.")

    try:
        caps = doctor.probe(config)
    except Exception as exc:
        console.error(f"capability probe failed: {exc}")
        return 1
    console.write()
    console.write(doctor.render(caps, config, path))
    missing = bool(doctor.missing_required(caps))
    if missing:
        console.write("Service restart skipped until required capabilities are available.")
        return followup_exit_code(operational_failure=operational_failure, missing_required=True)

    if restart_eligible(
        config_changed=changed,
        custom_config=custom_config,
        missing_required=False,
        service_active=caps.service_active,
    ):
        if _ask_yes_no(
            console, "Restart the active stenographer.service to apply changes?", default=True
        ) and not _restart_service(console):
            operational_failure = True
    elif changed and custom_config:
        console.write("Custom STENOGRAPHER_CONFIG path: service restart was not offered.")
    elif changed and caps.service_active != "active":
        if caps.service_enabled is None:
            console.write("Service is not installed; run scripts/install.sh when ready.")
        else:
            console.write(
                "Service is not active; setup did not start it. "
                "Run `systemctl --user start stenographer.service` when ready."
            )
    return followup_exit_code(operational_failure=operational_failure, missing_required=False)


def run(
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run the TTY-only setup wizard and guided capability checks."""

    input_stream = sys.stdin if stdin is None else stdin
    output_stream = sys.stdout if stdout is None else stdout
    error_stream = sys.stderr if stderr is None else stderr
    console = _Console(input_stream, output_stream, error_stream)
    if not input_stream.isatty() or not output_stream.isatty():
        console.error("setup requires an interactive terminal")
        return 2

    from stenographer.config import resolve_config_path

    path = resolve_config_path(create_parent=False)
    custom_config = bool(os.environ.get("STENOGRAPHER_CONFIG"))
    try:
        document = ConfigDocument.load(path)
    except ConfigError as exc:
        console.error(str(exc))
        return 78
    except ConfigPersistenceError as exc:
        console.error(str(exc))
        return 1
    except KeyboardInterrupt:
        console.write()
        console.error("setup interrupted")
        return 130

    console.write("Stenographer setup")
    console.write(f"Configuration: {path}")
    console.write("Press Enter to retain each current value.")
    try:
        reviewed = _wizard(console, document.config)
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
    if result.changed:
        console.write(f"Saved {result.path}")
        if result.backup_path is not None:
            console.write(f"Backup: {result.backup_path}")
    else:
        console.write("Configuration is unchanged; no file was written.")

    try:
        return _guided_setup(
            console,
            reviewed,
            path,
            changed=result.changed,
            custom_config=custom_config,
        )
    except (KeyboardInterrupt, EOFError):
        console.write()
        console.error("setup interrupted; saved configuration was not rolled back")
        return 130
