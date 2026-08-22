# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only host probes behind ``doctor`` (spec §4.13) and the systemd restart.

Nothing here writes, opens a device, or touches the network; the probes feed
``doctor.Capabilities`` through :class:`~stenographer.platform.base.HostProbe`.
"""

from __future__ import annotations

import os
import shutil
import subprocess

from stenographer.platform.base import HostProbe
from stenographer.platform.linux.clipboard import probe_clipboard
from stenographer.platform.linux.cues import detect_player


def uinput_writable() -> bool:
    return os.access("/dev/uinput", os.W_OK)


def in_input_group() -> bool:
    if os.geteuid() == 0:
        return True
    import grp

    try:
        input_gid = grp.getgrnam("input").gr_gid
    except KeyError:
        return False
    return input_gid in os.getgroups()


def service_status() -> tuple[str | None, str | None]:
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


def restart_service() -> tuple[bool, str]:
    """``systemctl --user restart stenographer.service``; ``(ok, detail)``."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "restart", "stenographer.service"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return (False, str(exc))
    if result.returncode != 0:
        return (False, result.stderr.strip() or f"systemctl exited {result.returncode}")
    return (True, "")


def probe_host() -> HostProbe:
    """The platform half of ``doctor.Capabilities``; read-only."""
    service_enabled, service_active = service_status()
    clipboard_ok, clipboard_backend = probe_clipboard()
    return HostProbe(
        key_injector_ok=uinput_writable(),
        hotkey_access_ok=in_input_group(),
        clipboard_ok=clipboard_ok,
        clipboard_backend=clipboard_backend,
        cue_player=detect_player(),
        service_enabled=service_enabled,
        service_active=service_active,
    )
