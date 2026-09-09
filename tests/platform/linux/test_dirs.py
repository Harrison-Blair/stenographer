# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure environment resolution for the Linux provider: XDG dirs, journal."""

from __future__ import annotations

from pathlib import Path

from stenographer.platform.linux.dirs import (
    config_path,
    journal_attached,
    runtime_dir,
    state_dir,
)


def test_config_path_prefers_xdg_config_home():
    assert config_path({"XDG_CONFIG_HOME": "/cfg"}, Path("/home/alice")) == Path(
        "/cfg/stenographer/config.toml"
    )


def test_config_path_falls_back_below_home():
    assert config_path({}, Path("/home/alice")) == Path(
        "/home/alice/.config/stenographer/config.toml"
    )


def test_resolve_state_dir_prefers_xdg_state_home():
    assert state_dir({"XDG_STATE_HOME": "/state"}, Path("/home/alice")) == Path(
        "/state/stenographer"
    )


def test_resolve_state_dir_falls_back_below_home():
    assert state_dir({}, Path("/home/alice")) == Path("/home/alice/.local/state/stenographer")


def test_runtime_dir_prefers_xdg_runtime_dir():
    assert runtime_dir({"XDG_RUNTIME_DIR": "/run/user/1000"}) == Path("/run/user/1000")


def test_runtime_dir_falls_back_to_run_user_uid():
    assert runtime_dir({}).parent == Path("/run/user")


def test_journal_attached_follows_the_systemd_variable():
    """systemd sets JOURNAL_STREAM for a unit whose stderr is the journal.

    Seen to FAIL against a probe keyed on ``INVOCATION_ID`` (true for any
    systemd-started unit, journal or not).
    """

    assert journal_attached({"JOURNAL_STREAM": "8:123456"}) is True
    assert journal_attached({"INVOCATION_ID": "abc"}) is False
    assert journal_attached({}) is False
