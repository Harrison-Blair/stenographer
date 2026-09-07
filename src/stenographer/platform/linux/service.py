# SPDX-License-Identifier: GPL-3.0-or-later
"""Installed user-service status and detached, bounded service actions."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping

from stenographer.platform.base import ServiceStatus

_UNIT = "stenographer.service"


def service_status() -> ServiceStatus:
    if not shutil.which("systemctl"):
        return ServiceStatus(False, detail="The systemd user service manager is unavailable.")
    try:
        result = subprocess.run(
            [
                "systemctl",
                "--user",
                "show",
                _UNIT,
                "--property=LoadState,ActiveState,UnitFileState",
            ],
            capture_output=True,
            text=True,
            timeout=3,
        )
        properties = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        if result.returncode or properties.get("LoadState") != "loaded":
            return ServiceStatus(False, detail="The user service is not installed or accessible.")
        return ServiceStatus(True, properties.get("ActiveState"), properties.get("UnitFileState"))
    except (OSError, subprocess.TimeoutExpired):
        return ServiceStatus(False, detail="The user service manager did not respond.")


def service_action(action: str) -> tuple[bool, str]:
    if action not in {"start", "stop", "restart", "enable", "disable"}:
        return False, "Unknown service action."
    status = service_status()
    if not status.available:
        return False, status.detail
    try:
        # The manager owns --no-block jobs after acceptance. No GUI child or
        # daemon thread must survive for a stop/restart job to finish.
        result = subprocess.run(
            ["systemctl", "--user", "--no-block", action, _UNIT],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            start_new_session=True,
        )
        return result.returncode == 0, (
            "Service action accepted."
            if result.returncode == 0
            else "The service manager rejected the action."
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, "The service action could not be submitted."


def restart_targets_process(properties: Mapping[str, str], pid: int) -> bool:
    """Pure admission: an installed unit is insufficient to own this daemon."""
    return (
        pid > 0
        and properties.get("LoadState") == "loaded"
        and properties.get("ActiveState") == "active"
        and properties.get("MainPID") == str(pid)
    )


def restart_running_service() -> tuple[bool, str]:
    """Refuse restarting an unrelated service from a manually launched daemon.

    The current process must be the active unit's MainPID. Once submitted, the
    manager owns the asynchronous restart job even if the control client exits.
    """
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show", _UNIT, "--property=LoadState,ActiveState,MainPID"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        properties = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        if result.returncode or not restart_targets_process(properties, os.getpid()):
            return False, (
                "This daemon was not started by its user service. Stop it and start it again "
                "to load saved settings."
            )
    except (OSError, subprocess.TimeoutExpired):
        return False, "Could not establish that the user service owns this daemon."
    return service_action("restart")
