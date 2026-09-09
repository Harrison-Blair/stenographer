# SPDX-License-Identifier: GPL-3.0-or-later
"""Linux prose the core prints: uinput/input-group hints, systemd commands.

Every Linux-only sentence fragment the CLI shows a user lives here rather than
in ``cli/doctor.py``, ``cli/setup.py``, ``cli/sounds.py``, or ``config.py``.
Pure and stdlib-only: no probe, no subprocess, no device.
"""

from __future__ import annotations

import shlex

from stenographer.platform.base import HostGuidance
from stenographer.status import UnavailableReason

_UNIT = "stenographer.service"
_XCLIP_HINT = "install xclip (the compositor lacks a data-control protocol; GNOME 46 and older)"
_WL_CLIPBOARD_HINT = "install wl-clipboard"


def run_with_config(path: str) -> str:
    """The POSIX shell line that runs the daemon against an explicit config path."""

    return f"STENOGRAPHER_CONFIG={shlex.quote(path)} stenographer run"


def guidance() -> HostGuidance:
    """The Linux/Wayland wording for every host-specific message the core prints."""

    return HostGuidance(
        capability_labels={
            "key_injector_ok": "/dev/uinput writable",
            "hotkey_access_ok": "input group membership",
            "has_mic": "microphone",
            "model_cached": "ASR model cached",
            "clipboard_ok": "clipboard",
        },
        capability_fix_hints={
            "key_injector_ok": (
                "grant write access to /dev/uinput (udev rule or the uinput group), then re-login"
            ),
            "hotkey_access_ok": "sudo usermod -aG input $USER, then re-login",
            "has_mic": "no audio input device found; check the microphone / PortAudio",
            "model_cached": "run: stenographer model download",
        },
        clipboard_fix_hints={"wl-copy": _WL_CLIPBOARD_HINT, "x11": _XCLIP_HINT},
        clipboard_fix_hint_default=_WL_CLIPBOARD_HINT,
        overlay_backend_labels={"layer-shell": "layer-shell", "xwayland": "XWayland fallback"},
        overlay_fix_hints={
            UnavailableReason.NO_X_DISPLAY: "no X display; set DISPLAY or enable XWayland",
            UnavailableReason.X_CONNECT_FAILED: (
                "cannot connect to XWayland; check DISPLAY and session access"
            ),
            UnavailableReason.X_ARGB_UNAVAILABLE: "XWayland has no usable 32-bit ARGB visual",
            UnavailableReason.X_EXTENSIONS_UNAVAILABLE: (
                "XWayland requires the Shape and RandR extensions"
            ),
            UnavailableReason.BACKEND_DEPENDENCY_MISSING: (
                "overlay backend imports failed; reinstall stenographer with its overlay extras"
            ),
        },
        overlay_fix_hint_default=(
            "no usable layer-shell or XWayland backend; check the graphical session"
        ),
        service_noun="systemd unit",
        service_name=_UNIT,
        service_installer="scripts/install.sh",
        service_unknown_detail="cannot query the systemd user manager",
        service_start_command=f"systemctl --user start {_UNIT}",
        service_restart_command=f"systemctl --user restart {_UNIT}",
        service_log_command="journalctl --user -u stenographer -f",
        hotkey_device_comment='explicit /dev/input/event* path; "" = auto-detect',
        run_with_config=run_with_config,
    )
