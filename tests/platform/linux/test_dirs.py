# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure XDG directory resolution for the Linux provider."""

from __future__ import annotations

from pathlib import Path

from stenographer.platform.linux.dirs import config_path, runtime_dir, state_dir


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
