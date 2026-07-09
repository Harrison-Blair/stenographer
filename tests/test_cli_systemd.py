# SPDX-License-Identifier: GPL-3.0-or-later
"""systemd lifecycle subcommands: enable / disable / start / stop."""

import pathlib

import pytest

import stenographer.cli as cli


def _fake_run(calls: list):
    def _run(args, check=False, **kw):
        calls.append(list(args))

        class _R:
            returncode = 0

        return _R()

    return _run


def test_enable_writes_unit_and_enables_now(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unit = tmp_path / "systemd" / "user" / "stenographer.service"
    monkeypatch.setattr(cli, "_UNIT_PATH", unit)
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/systemctl")
    monkeypatch.setattr(cli, "_resolve_daemon_exec", lambda: "/opt/stenographer/stenographer run")
    calls: list = []
    monkeypatch.setattr(cli.subprocess, "run", _fake_run(calls))

    assert cli.cmd_enable(no_start=False) == 0

    content = unit.read_text()
    assert "ExecStart=/opt/stenographer/stenographer run" in content
    assert ["systemctl", "--user", "daemon-reload"] in calls
    assert ["systemctl", "--user", "enable", "--now", "stenographer.service"] in calls


def test_enable_no_start_omits_now(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    unit = tmp_path / "stenographer.service"
    monkeypatch.setattr(cli, "_UNIT_PATH", unit)
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/systemctl")
    monkeypatch.setattr(cli, "_resolve_daemon_exec", lambda: "/opt/stenographer/stenographer run")
    calls: list = []
    monkeypatch.setattr(cli.subprocess, "run", _fake_run(calls))

    assert cli.cmd_enable(no_start=True) == 0
    assert ["systemctl", "--user", "enable", "stenographer.service"] in calls
    assert ["systemctl", "--user", "enable", "--now", "stenographer.service"] not in calls


def test_enable_backs_up_existing_unit(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unit = tmp_path / "stenographer.service"
    unit.write_text("OLD UNIT\n")
    monkeypatch.setattr(cli, "_UNIT_PATH", unit)
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/systemctl")
    monkeypatch.setattr(cli, "_resolve_daemon_exec", lambda: "/opt/stenographer/stenographer run")
    monkeypatch.setattr(cli.subprocess, "run", _fake_run([]))

    assert cli.cmd_enable(no_start=False) == 0
    backup = tmp_path / "stenographer.service.bak"
    assert backup.read_text() == "OLD UNIT\n"
    assert "ExecStart=/opt/stenographer/stenographer run" in unit.read_text()


def test_enable_fails_without_systemctl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli.shutil, "which", lambda _: None)
    assert cli.cmd_enable(no_start=False) == 1


def test_start_errors_when_unit_missing(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_UNIT_PATH", tmp_path / "stenographer.service")
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/systemctl")
    calls: list = []
    monkeypatch.setattr(cli.subprocess, "run", _fake_run(calls))

    assert cli.cmd_start() == 1
    assert calls == []  # never touched systemctl


def test_start_starts_existing_unit(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unit = tmp_path / "stenographer.service"
    unit.write_text("[Unit]\n")
    monkeypatch.setattr(cli, "_UNIT_PATH", unit)
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/systemctl")
    calls: list = []
    monkeypatch.setattr(cli.subprocess, "run", _fake_run(calls))

    assert cli.cmd_start() == 0
    assert ["systemctl", "--user", "start", "stenographer.service"] in calls
