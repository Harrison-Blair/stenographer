# SPDX-License-Identifier: GPL-3.0-or-later
"""Six-step setup navigation and probes for the hub."""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.text import Text

from stenographer.cli.hub.selection import append_line
from stenographer.lib.transcribe.bark_download import MODEL_NAME

if TYPE_CHECKING:
    from stenographer.cli.hub.setup_state import SetupWizard
    from stenographer.lib.config.models import Config


@dataclass(frozen=True)
class SetupStep:
    step_id: str
    title: str
    description: str
    config_key: str | None = None


SETUP_STEPS = (
    SetupStep(
        "input_access",
        "input access",
        "Check keyboard injection and global hotkey access.",
    ),
    SetupStep(
        "microphone",
        "microphone",
        "Select an input device. The test only lists devices; it does not capture audio.",
        "audio.input_device",
    ),
    SetupStep(
        "hotkey",
        "hotkey",
        "Set the push-to-talk binding. The test validates the binding and input access.",
        "hotkey.binding",
    ),
    SetupStep(
        "models",
        "models",
        f"Check the cached speech model ({MODEL_NAME}) and the live models. "
        "Downloads need a separate confirmation.",
    ),
    SetupStep(
        "sounds",
        "sounds",
        "Choose a sound pack and play its preview with the test key.",
        "feedback.sound_pack",
    ),
    SetupStep(
        "system_service",
        "system service",
        "Check the user service. Setup does not start or restart it.",
    ),
)


def render(wizard: SetupWizard, config: Config | None) -> Text:
    """Render the current wizard state and the settings owned by this step."""
    lines = Text()
    append_line(lines, "Quick setup · steps 1-3" if wizard.quick else "Setup wizard · 6 steps")
    append_line(lines, "")
    for index, step in enumerate(wizard.steps, 1):
        selected = index - 1 == wizard.index and not wizard.finished
        if selected:
            status = ""
        elif step.step_id in wizard.completed:
            status = "✓ "
        elif step.step_id in wizard.skipped:
            status = "- "
        else:
            status = "○ "
        append_line(
            lines,
            f"{status}{index} {step.title}",
            selectable=selected,
            selected=selected,
        )
    if wizard.finished:
        append_line(lines, "")
        append_line(lines, "Setup path complete.")
        return lines
    step = wizard.step
    append_line(lines, "")
    append_line(lines, f"{step.title}: {step.description}")
    if step.config_key is not None and config is not None:
        group, _, key = step.config_key.partition(".")
        value = getattr(getattr(config, group), key)
        shown = "automatic" if value is None else str(value)
        append_line(lines, f"Current {step.config_key}: {shown}")
    if wizard.last_test:
        append_line(lines, f"Test: {wizard.last_test}")
    append_line(lines, "")
    append_line(lines, "enter next   b back   s skip   t test   e edit   D write defaults")
    if step.step_id == "models":
        append_line(lines, "m download model (asks for confirmation)")
    if not wizard.quick:
        append_line(lines, "Q quick path (steps 1-3)")
    return lines


def test_step(step_id: str, config: Config, config_dir: pathlib.Path) -> str:
    """Run the selected setup test without opening a microphone or downloading."""
    from stenographer.cli.setup import workflow
    from stenographer.lib.platform import current_platform

    if step_id == "input_access":
        host = current_platform().probe_host()
        return (
            f"keyboard injection {'available' if host.key_injector_ok else 'unavailable'}; "
            f"global hotkey {'available' if host.hotkey_access_ok else 'unavailable'}"
        )
    if step_id == "microphone":
        devices = workflow._audio_devices()
        return f"{len(devices)} input device(s) found; no audio was captured"
    if step_id == "hotkey":
        workflow._parse_binding(config.hotkey.binding)
        host = current_platform().probe_host()
        access = "available" if host.hotkey_access_ok else "unavailable"
        return f"{config.hotkey.binding} is valid; hotkey access {access}"
    if step_id == "models":
        from stenographer.lib.transcribe import bark_download

        cached = bark_download.is_model_cached()
        from stenographer.lib.diagnostics.additional_checks import live_models_check

        live = live_models_check()
        return f"ASR model {'cached' if cached else 'not cached'}; live models {live.status}"
    if step_id == "sounds":
        from stenographer.lib.sounds import packs, playback

        pack = packs.load_sound_pack(config.feedback.sound_pack, config_dir)
        player = current_platform().cue_player()
        if pack is None or player is None:
            return "sound preview is unavailable"
        playback.preview_sound_pack(pack, player, playback.preview_volume(config.feedback))
        return f"Played the {config.feedback.sound_pack} sound preview"
    if step_id == "system_service":
        host = current_platform().probe_host()
        enabled = host.service_enabled or "not installed"
        active = host.service_active or "unknown"
        return f"service: {enabled}, {active}"
    raise ValueError(f"unknown setup step: {step_id}")
