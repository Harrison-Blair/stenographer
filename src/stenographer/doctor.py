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
import subprocess

from stenographer.config import Config
from stenographer.status import Backend, UnavailableReason


@dataclasses.dataclass(frozen=True, slots=True)
class OverlayCapability:
    """Informational result of the optional display-backend probe."""

    enabled: bool
    backend: Backend | None = None
    reason: UnavailableReason | None = None

    @classmethod
    def disabled(cls) -> OverlayCapability:
        return cls(False)

    @classmethod
    def available(cls, backend: Backend) -> OverlayCapability:
        return cls(True, backend=backend)

    @classmethod
    def unavailable(cls, reason: UnavailableReason) -> OverlayCapability:
        return cls(True, reason=reason)


@dataclasses.dataclass(frozen=True)
class Capabilities:
    uinput_writable: bool
    input_group: bool
    has_mic: bool
    model_cached: bool
    clipboard: bool
    clipboard_backend: str
    audio_player: str | None
    service_enabled: str | None
    service_active: str | None
    overlay: OverlayCapability = dataclasses.field(default_factory=OverlayCapability.disabled)


REQUIRED: tuple[str, ...] = (
    "uinput_writable",
    "input_group",
    "has_mic",
    "model_cached",
    "clipboard",
)

_FIX_HINTS = {
    "uinput_writable": (
        "grant write access to /dev/uinput (udev rule or the uinput group), then re-login"
    ),
    "input_group": "sudo usermod -aG input $USER, then re-login",
    "has_mic": "no audio input device found; check the microphone / PortAudio",
    "model_cached": "run: stenographer model download",
}

_CLIPBOARD_FIX_HINTS = {
    "wl-copy": "install wl-clipboard",
    "x11": "install xclip (the compositor lacks a data-control protocol; GNOME 46 and older)",
}

_LABELS = {
    "uinput_writable": "/dev/uinput writable",
    "input_group": "input group membership",
    "has_mic": "microphone",
    "model_cached": "ASR model cached",
    "clipboard": "clipboard",
}

_OVERLAY_FIX_HINTS = {
    UnavailableReason.NO_X_DISPLAY: "no X display; set DISPLAY or enable XWayland",
    UnavailableReason.X_CONNECT_FAILED: (
        "cannot connect to XWayland; check DISPLAY and session access"
    ),
    UnavailableReason.X_ARGB_UNAVAILABLE: "XWayland has no usable 32-bit ARGB visual",
    UnavailableReason.X_EXTENSIONS_UNAVAILABLE: (
        "XWayland requires the Shape and RandR extensions"
    ),
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


def _service_status() -> tuple[str | None, str | None]:
    """(`is-enabled`, `is-active`) of the systemd user unit; None per failed query.

    `is-enabled` prints nothing for an uninstalled unit while `is-active` still
    says "inactive"; an unreachable user manager yields (None, None).
    """
    if shutil.which("systemctl") is None:
        return (None, None)

    def query(verb: str) -> str | None:
        try:
            proc = subprocess.run(
                ["systemctl", "--user", verb, "stenographer.service"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return proc.stdout.strip() or None

    return (query("is-enabled"), query("is-active"))


def probe_overlay(enabled: bool) -> OverlayCapability:
    """Probe optional backends in runtime preference order without creating a surface."""
    if not enabled:
        return OverlayCapability.disabled()

    try:
        from stenographer.overlay_wayland import LayerShellBackend, WaylandUnavailableError

        try:
            backend = LayerShellBackend()
        except WaylandUnavailableError:
            pass
        else:
            backend.close()
            return OverlayCapability.available(Backend.LAYER_SHELL)
    except Exception:
        # Generated bindings or PyWayland may be unavailable in a partial
        # source environment.  XWayland remains a valid independent fallback.
        pass

    try:
        from stenographer.overlay_x11 import probe_x11

        reason = probe_x11()
    except Exception:
        reason = UnavailableReason.BACKENDS_UNAVAILABLE
    if reason is None:
        return OverlayCapability.available(Backend.XWAYLAND)
    return OverlayCapability.unavailable(reason)


def _probe_clipboard() -> tuple[bool, str]:
    """(needed binary present, detected backend name) for the delivery copy path."""
    from stenographer.deliver import ClipboardBackend, detect_clipboard_backend

    backend = detect_clipboard_backend()
    binary = "xclip" if backend is ClipboardBackend.X11 else "wl-copy"
    return shutil.which(binary) is not None, backend.value


def probe(cfg: Config) -> Capabilities:
    """Read-only environment probe: no writes, no network, no device opens."""
    from stenographer import feedback, model

    service_enabled, service_active = _service_status()
    clipboard_ok, clipboard_backend = _probe_clipboard()
    return Capabilities(
        uinput_writable=os.access("/dev/uinput", os.W_OK),
        input_group=_in_input_group(),
        has_mic=_has_mic(),
        model_cached=model.is_model_cached(cfg.asr.model),
        clipboard=clipboard_ok,
        clipboard_backend=clipboard_backend,
        audio_player=feedback.detect_player(),
        service_enabled=service_enabled,
        service_active=service_active,
        overlay=probe_overlay(cfg.feedback.overlay),
    )


def format_service_status(enabled: str | None, active: str | None) -> str:
    """Pure: one-line summary of the systemd user unit's state."""
    if enabled is None and active is None:
        return "unknown (cannot query the systemd user manager)"
    if enabled is None:
        return "not installed — run scripts/install.sh"
    return f"{enabled}, {active or 'unknown'}"


def format_overlay_status(capability: OverlayCapability) -> str:
    """Pure one-line status for an optional overlay capability."""
    if not capability.enabled:
        return "disabled"
    if capability.backend is Backend.LAYER_SHELL:
        return "layer-shell"
    if capability.backend is Backend.XWAYLAND:
        return "XWayland fallback"
    reason = capability.reason or UnavailableReason.BACKENDS_UNAVAILABLE
    hint = _OVERLAY_FIX_HINTS.get(
        reason, "no usable layer-shell or XWayland backend; check the graphical session"
    )
    return f"unavailable — {hint}"


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
        label = _LABELS[name]
        if name == "clipboard":
            label = f"clipboard ({caps.clipboard_backend})"
        line = f"  {label}: {'ok' if ok else 'MISSING'}"
        if not ok:
            hint = (
                _CLIPBOARD_FIX_HINTS.get(caps.clipboard_backend, _CLIPBOARD_FIX_HINTS["wl-copy"])
                if name == "clipboard"
                else _FIX_HINTS[name]
            )
            line += f" — {hint}"
        lines.append(line)
    player = caps.audio_player or "none (sound cues disabled)"
    lines.append(f"  audio player: {player}")
    service = format_service_status(caps.service_enabled, caps.service_active)
    lines.append(f"  systemd unit: {service}")
    lines.append(f"  overlay: {format_overlay_status(caps.overlay)}")
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
