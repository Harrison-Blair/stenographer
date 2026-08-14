# SPDX-License-Identifier: GPL-3.0-or-later
"""Capability probe behind the `doctor` subcommand.

The environment probing lives in :func:`probe`; the exit-78 decision
(:func:`missing_required`) and the report rendering (:func:`render`) are pure
so they are unit-testable without mocking the environment (spec §6.5).
"""

from __future__ import annotations

import dataclasses
import os
import pathlib
import shutil

from stenographer.config import Config


@dataclasses.dataclass(frozen=True)
class Capabilities:
    uinput_writable: bool
    input_group: bool
    has_mic: bool
    model_cached: bool
    wl_copy: bool
    audio_player: str | None


REQUIRED: tuple[str, ...] = ("uinput_writable", "input_group", "has_mic", "model_cached", "wl_copy")

_FIX_HINTS = {
    "uinput_writable": (
        "grant write access to /dev/uinput (udev rule or the uinput group), then re-login"
    ),
    "input_group": "sudo usermod -aG input $USER, then re-login",
    "has_mic": "no audio input device found; check the microphone / PortAudio",
    "model_cached": "run: stenographer model download",
    "wl_copy": "install wl-clipboard",
}

_LABELS = {
    "uinput_writable": "/dev/uinput writable",
    "input_group": "input group membership",
    "has_mic": "microphone",
    "model_cached": "ASR model cached",
    "wl_copy": "wl-copy",
}


def _in_input_group() -> bool:
    if os.geteuid() == 0:
        return True
    import grp

    try:
        input_gid = grp.getgrnam("input").gr_gid
    except KeyError:
        return False
    return input_gid in os.getgroups()


def _has_mic() -> bool:
    import sounddevice

    try:
        devices = sounddevice.query_devices()
    except sounddevice.PortAudioError:
        return False
    return any(d.get("max_input_channels", 0) > 0 for d in devices)


def probe(cfg: Config) -> Capabilities:
    """Read-only environment probe: no writes, no network, no device opens."""
    from stenographer import feedback, model

    return Capabilities(
        uinput_writable=os.access("/dev/uinput", os.W_OK),
        input_group=_in_input_group(),
        has_mic=_has_mic(),
        model_cached=model.is_model_cached(cfg.asr.model),
        wl_copy=shutil.which("wl-copy") is not None,
        audio_player=feedback.detect_player(),
    )


def missing_required(caps: Capabilities) -> list[str]:
    """Pure: names of REQUIRED capabilities that are absent."""
    return [name for name in REQUIRED if not getattr(caps, name)]


def render(caps: Capabilities, cfg: Config, config_path: pathlib.Path) -> str:
    """Pure: the doctor report, with an exact fix hint per missing capability."""
    lines = [
        f"config: {config_path}",
        f"model: {cfg.asr.model}",
        f"hotkey binding: {cfg.hotkey.binding}",
        "",
    ]
    for name in REQUIRED:
        ok = bool(getattr(caps, name))
        line = f"  {_LABELS[name]}: {'ok' if ok else 'MISSING'}"
        if not ok:
            line += f" — {_FIX_HINTS[name]}"
        lines.append(line)
    player = caps.audio_player or "none (sound cues disabled)"
    lines.append(f"  audio player: {player}")
    lines.append("")
    missing = missing_required(caps)
    if missing:
        lines.append(f"missing required capabilities: {', '.join(missing)}")
    else:
        lines.append("all required capabilities present")
    return "\n".join(lines)


def run(cfg: Config, config_path: pathlib.Path) -> int:
    caps = probe(cfg)
    print(render(caps, cfg, config_path))
    return 78 if missing_required(caps) else 0
