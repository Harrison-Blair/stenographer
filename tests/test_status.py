# SPDX-License-Identifier: GPL-3.0-or-later
"""Lifecycle status collection and rendering."""

from __future__ import annotations

import pathlib
import subprocess

import pytest

import stenographer.status as status_mod
from stenographer._parser import build_parser


def _completed(
    args: list[str],
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr=stderr)


def _systemd_status(**overrides: object) -> status_mod.SystemdStatus:
    values: dict[str, object] = {
        "available": True,
        "load_state": "loaded",
        "fragment_path": "/home/test/.config/systemd/user/stenographer.service",
        "unit_file_state": "enabled",
        "active_state": "active",
        "sub_state": "running",
        "main_pid": 1234,
        "preview": "● stenographer.service\n   Active: active (running)",
    }
    values.update(overrides)
    return status_mod.SystemdStatus(**values)


def test_collect_systemd_status_includes_plain_ten_line_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(status_mod.shutil, "which", lambda _: "/usr/bin/systemctl")
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((args, kwargs))
        if "show" in args:
            return _completed(
                args,
                stdout=(
                    "LoadState=loaded\n"
                    "FragmentPath=/home/test/.config/systemd/user/stenographer.service\n"
                    "UnitFileState=enabled\n"
                    "ActiveState=active\n"
                    "SubState=running\n"
                    "MainPID=1234\n"
                ),
            )
        return _completed(args, returncode=3, stdout="● stenographer.service\n   Active: inactive")

    monkeypatch.setattr(status_mod.subprocess, "run", fake_run)

    result = status_mod.collect_systemd_status()

    assert result.available is True
    assert result.main_pid == 1234
    assert result.preview.endswith("Active: inactive")
    preview_args, preview_kwargs = calls[1]
    assert preview_args == [
        "systemctl",
        "--user",
        "status",
        "stenographer.service",
        "--no-pager",
        "--full",
        "--lines=10",
    ]
    env = preview_kwargs["env"]
    assert isinstance(env, dict)
    assert env["SYSTEMD_COLORS"] == "0"
    assert env["SYSTEMD_PAGER"] == "cat"
    assert preview_kwargs["timeout"] == 5


def test_collect_systemd_status_handles_missing_systemctl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(status_mod.shutil, "which", lambda _: None)

    result = status_mod.collect_systemd_status()

    assert result.available is False
    assert "not available" in result.preview


def test_collect_systemd_status_handles_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status_mod.shutil, "which", lambda _: "/usr/bin/systemctl")

    def timeout(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="systemctl", timeout=5)

    monkeypatch.setattr(status_mod.subprocess, "run", timeout)

    result = status_mod.collect_systemd_status()

    assert result.available is False
    assert result.error == "systemctl timed out after 5s"


def test_collect_systemd_status_preserves_missing_unit_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(status_mod.shutil, "which", lambda _: "/usr/bin/systemctl")

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "show" in args:
            return _completed(args, returncode=1, stderr="Unit not found")
        return _completed(
            args, returncode=4, stderr="Unit stenographer.service could not be found."
        )

    monkeypatch.setattr(status_mod.subprocess, "run", fake_run)

    result = status_mod.collect_systemd_status()

    assert result.available is False
    assert result.error == "Unit not found"
    assert result.preview == "Unit stenographer.service could not be found."


def test_collect_runtime_lock_reports_stale_pid(tmp_path: pathlib.Path) -> None:
    lock_path = tmp_path / "stenographer.lock"
    lock_path.write_text("1234\n")

    result = status_mod.collect_runtime_lock(lock_path)

    assert result == status_mod.RuntimeLockStatus("stale (PID 1234)", pid=1234)
    assert lock_path.exists()


def test_collect_runtime_lock_reports_held_pid(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock_path = tmp_path / "stenographer.lock"
    lock_path.write_text("1234\n")

    def locked(*args: object) -> None:
        raise BlockingIOError

    monkeypatch.setattr(status_mod.fcntl, "flock", locked)

    result = status_mod.collect_runtime_lock(lock_path)

    assert result == status_mod.RuntimeLockStatus("held", held=True, pid=1234)


def test_collect_status_prefers_live_systemd_process(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unit_path = tmp_path / "stenographer.service"
    monkeypatch.setattr(status_mod, "collect_systemd_status", _systemd_status)
    monkeypatch.setattr(
        status_mod,
        "collect_runtime_lock",
        lambda _: status_mod.RuntimeLockStatus("held", held=True, pid=1234),
    )
    monkeypatch.setattr(status_mod, "_pid_exists", lambda pid: pid == 1234)
    monkeypatch.setattr(status_mod, "process_uptime", lambda _: 3723.8)

    result = status_mod.collect_status(tmp_path / "lock", unit_path)

    assert result.running is True
    assert result.manager == "systemd"
    assert result.pid == 1234
    assert result.uptime_seconds == 3723.8
    assert result.unit_path == pathlib.Path("/home/test/.config/systemd/user/stenographer.service")


def test_collect_status_detects_foreground_daemon_without_systemd(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        status_mod,
        "collect_systemd_status",
        lambda: _systemd_status(
            available=False,
            fragment_path="",
            unit_file_state="unknown",
            active_state="unknown",
            sub_state="unknown",
            main_pid=None,
            preview="(systemctl unavailable)",
        ),
    )
    monkeypatch.setattr(
        status_mod,
        "collect_runtime_lock",
        lambda _: status_mod.RuntimeLockStatus("held", held=True, pid=4321),
    )
    monkeypatch.setattr(status_mod, "_pid_exists", lambda pid: pid == 4321)
    monkeypatch.setattr(status_mod, "process_uptime", lambda _: 65.0)

    result = status_mod.collect_status(tmp_path / "lock", tmp_path / "unit")

    assert result.running is True
    assert result.manager == "foreground"
    assert result.pid == 4321


def test_collect_status_reports_failed_service_as_stopped(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        status_mod,
        "collect_systemd_status",
        lambda: _systemd_status(
            unit_file_state="disabled",
            active_state="failed",
            sub_state="failed",
            main_pid=None,
        ),
    )
    monkeypatch.setattr(
        status_mod,
        "collect_runtime_lock",
        lambda _: status_mod.RuntimeLockStatus("stale (PID 9999)", pid=9999),
    )
    monkeypatch.setattr(status_mod, "_pid_exists", lambda _: False)

    result = status_mod.collect_status(tmp_path / "lock", tmp_path / "unit")

    assert result.running is False
    assert result.manager is None
    assert result.pid is None


def test_render_status_shows_lifecycle_and_preview() -> None:
    report = status_mod.DaemonStatus(
        running=True,
        manager="systemd",
        pid=1234,
        uptime_seconds=93_784,
        unit_path=pathlib.Path("/home/test/stenographer.service"),
        systemd=_systemd_status(),
        runtime_lock=status_mod.RuntimeLockStatus("held", held=True, pid=1234),
    )

    output = status_mod.render_status(report)

    assert "daemon:       running" in output
    assert "manager:      systemd" in output
    assert "uptime:       1d 2h 3m 4s" in output
    assert "enabled:      yes (enabled)" in output
    assert "systemd:      active (running)" in output
    assert "systemd status preview" in output
    assert "● stenographer.service" in output


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0s"),
        (59.9, "59s"),
        (60, "1m 0s"),
        (3_661, "1h 1m 1s"),
        (None, "unknown"),
    ],
)
def test_format_uptime(seconds: float | None, expected: str) -> None:
    assert status_mod.format_uptime(seconds) == expected


def test_cmd_status_exit_code_tracks_live_daemon(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: pathlib.Path,
) -> None:
    stopped = status_mod.DaemonStatus(
        running=False,
        manager=None,
        pid=None,
        uptime_seconds=None,
        unit_path=None,
        systemd=_systemd_status(
            fragment_path="",
            unit_file_state="disabled",
            active_state="inactive",
            sub_state="dead",
            main_pid=None,
        ),
        runtime_lock=status_mod.RuntimeLockStatus("absent"),
    )
    monkeypatch.setattr(status_mod, "collect_status", lambda *_: stopped)

    assert status_mod.cmd_status(tmp_path / "lock", tmp_path / "unit") == 1
    assert "daemon:       stopped" in capsys.readouterr().out


def test_parser_accepts_status_subcommand() -> None:
    args = build_parser().parse_args(["status"])
    assert args.subcommand == "status"
