# SPDX-License-Identifier: GPL-3.0-or-later
"""Setup tests of the Checks tab; no test opens a microphone or downloads."""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stenographer.lib.config.models import Config


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
        from stenographer.cli.hub.doctor_view import DOCTOR_STATE_GLYPHS
        from stenographer.lib.audio.probe import input_device_choices, query_devices

        query = query_devices()
        if query.error is not None:
            return f"{DOCTOR_STATE_GLYPHS['fail']} no audio server; no audio was captured"
        devices = input_device_choices(query.devices)
        names = ", ".join(label for _value, label in devices) or "none"
        noun = "device" if len(devices) == 1 else "devices"
        return f"{len(devices)} input {noun}: {names}; no audio was captured"
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
