# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only lifecycle status collection for the Stenographer daemon.

The collector combines systemd user-unit metadata with the daemon's runtime
lock so foreground launches remain visible when no systemd unit is active.
It never creates, removes, or repairs either resource.
"""

from __future__ import annotations

import errno
import fcntl
import os
import pathlib
import shutil
import subprocess
from dataclasses import dataclass

_UNIT_NAME = "stenographer.service"
_SYSTEMD_PROPERTIES = (
    "LoadState",
    "FragmentPath",
    "UnitFileState",
    "ActiveState",
    "SubState",
    "MainPID",
)
_SYSTEMCTL_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class SystemdStatus:
    """A snapshot of the systemd user unit and its human-readable preview."""

    available: bool
    load_state: str = "unknown"
    fragment_path: str = ""
    unit_file_state: str = "unknown"
    active_state: str = "unknown"
    sub_state: str = "unknown"
    main_pid: int | None = None
    preview: str = "(systemd status unavailable)"
    error: str | None = None


@dataclass(frozen=True)
class RuntimeLockStatus:
    """A snapshot of the single-instance runtime lock."""

    state: str
    held: bool = False
    pid: int | None = None


@dataclass(frozen=True)
class DaemonStatus:
    """Combined daemon, systemd unit, and runtime-lock status."""

    running: bool
    manager: str | None
    pid: int | None
    uptime_seconds: float | None
    unit_path: pathlib.Path | None
    systemd: SystemdStatus
    runtime_lock: RuntimeLockStatus


def _systemctl_environment() -> dict[str, str]:
    """Return an environment that makes captured systemctl output readable."""
    return {
        **os.environ,
        "SYSTEMD_COLORS": "0",
        "SYSTEMD_PAGER": "cat",
    }


def _parse_systemd_properties(output: str) -> dict[str, str]:
    properties: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if separator and key in _SYSTEMD_PROPERTIES:
            properties[key] = value
    return properties


def _parse_pid(value: str | None) -> int | None:
    if value is None or not value.isdigit():
        return None
    pid = int(value)
    return pid if pid > 0 else None


def collect_systemd_status() -> SystemdStatus:
    """Collect stable unit properties and a ten-line ``systemctl status`` preview."""
    if shutil.which("systemctl") is None:
        return SystemdStatus(
            available=False,
            preview="(systemctl is not available)",
            error="systemctl is not available",
        )

    env = _systemctl_environment()
    property_arg = "--property=" + ",".join(_SYSTEMD_PROPERTIES)
    try:
        show_result = subprocess.run(
            ["systemctl", "--user", "show", _UNIT_NAME, "--no-pager", property_arg],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=_SYSTEMCTL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        message = f"systemctl timed out after {_SYSTEMCTL_TIMEOUT_SECONDS}s"
        return SystemdStatus(available=False, preview=f"({message})", error=message)
    except OSError as exc:
        message = f"cannot run systemctl: {exc}"
        return SystemdStatus(available=False, preview=f"({message})", error=message)

    properties = _parse_systemd_properties(show_result.stdout)
    show_error = None
    if show_result.returncode != 0:
        show_error = show_result.stderr.strip() or "systemctl show failed"

    try:
        preview_result = subprocess.run(
            [
                "systemctl",
                "--user",
                "status",
                _UNIT_NAME,
                "--no-pager",
                "--full",
                "--lines=10",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=_SYSTEMCTL_TIMEOUT_SECONDS,
        )
        preview = (
            preview_result.stdout.rstrip()
            or preview_result.stderr.rstrip()
            or "(systemctl status returned no output)"
        )
    except subprocess.TimeoutExpired:
        preview = f"(systemctl status timed out after {_SYSTEMCTL_TIMEOUT_SECONDS}s)"
    except OSError as exc:
        preview = f"(cannot run systemctl status: {exc})"

    return SystemdStatus(
        available=bool(properties),
        load_state=properties.get("LoadState", "unknown"),
        fragment_path=properties.get("FragmentPath", ""),
        unit_file_state=properties.get("UnitFileState", "unknown"),
        active_state=properties.get("ActiveState", "unknown"),
        sub_state=properties.get("SubState", "unknown"),
        main_pid=_parse_pid(properties.get("MainPID")),
        preview=preview,
        error=show_error,
    )


def collect_runtime_lock(lock_path: pathlib.Path) -> RuntimeLockStatus:
    """Inspect whether *lock_path* is held without creating or removing it."""
    if not lock_path.exists():
        return RuntimeLockStatus("absent")

    try:
        with lock_path.open(encoding="utf-8") as lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                try:
                    value = lock_file.read().strip()
                except OSError as exc:
                    return RuntimeLockStatus(f"held (cannot read PID: {exc})", held=True)
                pid = _parse_pid(value)
                if pid is None:
                    return RuntimeLockStatus("held (invalid PID)", held=True)
                return RuntimeLockStatus("held", held=True, pid=pid)
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EAGAIN):
                    return RuntimeLockStatus("held (PID unavailable)", held=True)
                return RuntimeLockStatus(f"unknown ({exc})")

            value = lock_file.read().strip()
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        return RuntimeLockStatus(f"unknown ({exc})")

    pid = _parse_pid(value)
    if pid is not None:
        return RuntimeLockStatus(f"stale (PID {pid})", pid=pid)
    if value:
        return RuntimeLockStatus("stale (invalid PID)")
    return RuntimeLockStatus("stale (empty)")


def _pid_exists(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_uptime(pid: int) -> float | None:
    """Return Linux process uptime in seconds, or ``None`` if it races with exit."""
    try:
        stat = pathlib.Path(f"/proc/{pid}/stat").read_text()
        closing_parenthesis = stat.rfind(")")
        fields_after_name = stat[closing_parenthesis + 2 :].split()
        start_ticks = int(fields_after_name[19])
        ticks_per_second = os.sysconf("SC_CLK_TCK")
        system_uptime = float(pathlib.Path("/proc/uptime").read_text().split()[0])
    except OSError, ValueError, IndexError:
        return None
    return max(0.0, system_uptime - (start_ticks / ticks_per_second))


def collect_status(lock_path: pathlib.Path, unit_path: pathlib.Path) -> DaemonStatus:
    """Return a combined point-in-time lifecycle report."""
    systemd = collect_systemd_status()
    runtime_lock = collect_runtime_lock(lock_path)

    systemd_live = systemd.active_state in {"active", "activating", "reloading"} and _pid_exists(
        systemd.main_pid
    )
    lock_live = runtime_lock.held and _pid_exists(runtime_lock.pid)

    if systemd_live:
        manager = "systemd"
        pid = systemd.main_pid
    elif lock_live:
        manager = "foreground"
        pid = runtime_lock.pid
    else:
        manager = None
        pid = None

    discovered_unit_path: pathlib.Path | None = None
    if systemd.fragment_path:
        discovered_unit_path = pathlib.Path(systemd.fragment_path)
    elif unit_path.is_file():
        discovered_unit_path = unit_path

    return DaemonStatus(
        running=pid is not None,
        manager=manager,
        pid=pid,
        uptime_seconds=process_uptime(pid) if pid is not None else None,
        unit_path=discovered_unit_path,
        systemd=systemd,
        runtime_lock=runtime_lock,
    )


def format_uptime(seconds: float | None) -> str:
    """Format an uptime duration as compact days, hours, minutes, and seconds."""
    if seconds is None:
        return "unknown"
    remaining = max(0, int(seconds))
    days, remaining = divmod(remaining, 86_400)
    hours, remaining = divmod(remaining, 3_600)
    minutes, seconds_part = divmod(remaining, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds_part}s")
    return " ".join(parts)


def _format_enabled(systemd: SystemdStatus) -> str:
    state = systemd.unit_file_state
    if state in {"enabled", "enabled-runtime"}:
        return f"yes ({state})"
    if state == "unknown" and systemd.load_state == "not-found":
        return "no (not installed)"
    if state == "unknown":
        return "unknown"
    return f"no ({state})"


def render_status(status: DaemonStatus) -> str:
    """Render a human-readable lifecycle report and systemd preview."""
    systemd_state = status.systemd.active_state
    if status.systemd.sub_state != "unknown":
        systemd_state += f" ({status.systemd.sub_state})"

    lines = [
        "stenographer status",
        "====================",
        f"daemon:       {'running' if status.running else 'stopped'}",
        f"manager:      {status.manager or 'none'}",
        f"pid:          {status.pid if status.pid is not None else '-'}",
        f"uptime:       {format_uptime(status.uptime_seconds) if status.running else '-'}",
        f"unit file:    {status.unit_path if status.unit_path is not None else 'not installed'}",
        f"enabled:      {_format_enabled(status.systemd)}",
        f"systemd:      {systemd_state}",
        f"runtime lock: {status.runtime_lock.state}",
        "",
        "systemd status preview",
        "======================",
        status.systemd.preview,
    ]
    return "\n".join(lines)


def cmd_status(lock_path: pathlib.Path, unit_path: pathlib.Path) -> int:
    """Print the current daemon status and return zero only when it is running."""
    status = collect_status(lock_path, unit_path)
    print(render_status(status))
    return 0 if status.running else 1
