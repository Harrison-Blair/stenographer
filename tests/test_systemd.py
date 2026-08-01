# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared systemd user-unit helpers."""

from __future__ import annotations

import pytest

from stenographer import systemd


def test_systemctl_argv_prefixes_user_manager() -> None:
    assert systemd.systemctl_argv("enable", systemd.UNIT_NAME) == [
        "systemctl",
        "--user",
        "enable",
        "stenographer.service",
    ]


def test_systemctl_argv_supports_bare_verb() -> None:
    assert systemd.systemctl_argv("daemon-reload") == [
        "systemctl",
        "--user",
        "daemon-reload",
    ]


def test_render_unit_embeds_exec_start() -> None:
    unit = systemd.render_unit("/opt/stenographer/stenographer run")

    assert "ExecStart=/opt/stenographer/stenographer run\n" in unit
    assert unit.startswith("[Unit]\n")
    assert "[Service]\n" in unit
    assert "[Install]\n" in unit
    assert "WantedBy=graphical-session.target\n" in unit


def test_resolve_daemon_exec_uses_path_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(systemd.sys, "frozen", False, raising=False)
    monkeypatch.setattr(systemd.shutil, "which", lambda _: "/home/user/.local/bin/stenographer")

    assert systemd.resolve_daemon_exec() == "/home/user/.local/bin/stenographer run"
