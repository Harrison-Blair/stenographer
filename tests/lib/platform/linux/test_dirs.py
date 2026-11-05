# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure environment resolution for the Linux provider: XDG dirs, journal."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from stenographer.lib.platform.linux.dirs import journal_attached, runtime_dir
from stenographer.lib.platform.linux.provider import LinuxPlatform


@pytest.mark.parametrize(
    ("method", "env", "expected"),
    [
        pytest.param(
            "config_path",
            {"XDG_CONFIG_HOME": "/cfg"},
            "/cfg/stenographer/config.toml",
            id="config_xdg",
        ),
        pytest.param(
            "config_path", {}, "/home/alice/.config/stenographer/config.toml", id="config_home"
        ),
        pytest.param(
            "state_dir", {"XDG_STATE_HOME": "/state"}, "/state/stenographer", id="state_xdg"
        ),
        pytest.param("state_dir", {}, "/home/alice/.local/state/stenographer", id="state_home"),
        pytest.param("data_dir", {"XDG_DATA_HOME": "/data"}, "/data/stenographer", id="data_xdg"),
        pytest.param("data_dir", {}, "/home/alice/.local/share/stenographer", id="data_home"),
    ],
)
def test_provider_resolves_xdg_directories(method, env, expected):
    assert getattr(LinuxPlatform(), method)(env, Path("/home/alice")) == Path(expected)


def test_runtime_dir_prefers_xdg_runtime_dir():
    assert runtime_dir({"XDG_RUNTIME_DIR": "/run/user/1000"}) == Path("/run/user/1000")


def test_runtime_dir_falls_back_to_run_user_uid():
    assert runtime_dir({}) == Path(f"/run/user/{os.getuid()}")


def test_journal_attached_follows_the_systemd_variable():
    """systemd sets JOURNAL_STREAM for a unit whose stderr is the journal.

    Seen to FAIL against a probe keyed on ``INVOCATION_ID`` (true for any
    systemd-started unit, journal or not).
    """

    assert journal_attached({"JOURNAL_STREAM": "8:123456"}) is True
    assert journal_attached({"INVOCATION_ID": "abc"}) is False
    assert journal_attached({}) is False
