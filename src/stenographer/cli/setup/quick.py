# SPDX-License-Identifier: GPL-3.0-or-later
"""Essential hotkey, microphone, and feedback setup."""

from __future__ import annotations

import dataclasses
import pathlib

from stenographer.cli.setup.errors import SetupCancelledError
from stenographer.cli.setup.workflow import (
    _audio_devices,
    _capture_or_choose_binding,
    _edit_feedback_section,
    _hotkey_devices,
    _prompt_choice,
    _prompt_device,
    parse_quick_review_action,
    quick_review_lines,
)
from stenographer.cli.shared.console import Console
from stenographer.lib.config.models import Config


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
    mode = _prompt_choice(console, "Trigger mode", config.hotkey.mode, ("hold", "toggle", "hybrid"))
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
        ask_log_level=False,
    )

    for line in quick_review_lines(config):
        console.write(line)
    action = console.validated("Save [Enter/S] or Cancel [C]: ", parse_quick_review_action)
    if action == "cancel":
        raise SetupCancelledError
    return config
