# SPDX-License-Identifier: GPL-3.0-or-later
"""Six-step setup navigation and probes for the hub."""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

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
        "Check cached speech and live models. Downloads need a separate confirmation.",
        "asr.model",
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


def render(wizard: SetupWizard, config: Config | None) -> str:
    """Render the current wizard state and the settings owned by this step."""
    lines = ["Quick setup · steps 1-3" if wizard.quick else "Setup wizard · 6 steps", ""]
    for index, step in enumerate(wizard.steps, 1):
        if step.step_id in wizard.completed:
            marker = "✓"
        elif step.step_id in wizard.skipped:
            marker = "-"
        else:
            marker = "▸" if index - 1 == wizard.index and not wizard.finished else "○"
        lines.append(f"{marker} {index} {step.title}")
    if wizard.finished:
        lines.extend(("", "Setup path complete."))
        return "\n".join(lines)
    step = wizard.step
    lines.extend(("", f"{step.title}: {step.description}"))
    if step.config_key is not None and config is not None:
        group, _, key = step.config_key.partition(".")
        value = getattr(getattr(config, group), key)
        shown = "automatic" if value is None else str(value)
        lines.append(f"Current {step.config_key}: {shown}")
    if wizard.last_test:
        lines.append(f"Test: {wizard.last_test}")
    lines.extend(("", "enter next   b back   s skip   t test   e edit   D write defaults"))
    if step.step_id == "models":
        lines.append("m download model (asks for confirmation)")
    if not wizard.quick:
        lines.append("Q quick path (steps 1-3)")
    return "\n".join(lines)


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
        from stenographer.lib.transcribe.download import is_model_cached

        cached = is_model_cached(config.asr.model)
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
