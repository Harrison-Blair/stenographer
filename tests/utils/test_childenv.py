# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for childenv._scrub: the PyInstaller LD_LIBRARY_PATH undo."""

from __future__ import annotations

from stenographer.utils.childenv import _scrub


def test_not_frozen_env_passes_through_unchanged():
    env = {"LD_LIBRARY_PATH": "/repo/.venv/lib", "PATH": "/usr/bin"}
    assert _scrub(env, frozen=False) == env


def test_frozen_restores_original_ld_library_path():
    env = {
        "LD_LIBRARY_PATH": "/opt/bundle/_internal",
        "LD_LIBRARY_PATH_ORIG": "/usr/local/cuda/lib64",
        "PATH": "/usr/bin",
    }
    assert _scrub(env, frozen=True) == {
        "LD_LIBRARY_PATH": "/usr/local/cuda/lib64",
        "PATH": "/usr/bin",
    }


def test_frozen_drops_injected_ld_library_path_when_no_original():
    env = {"LD_LIBRARY_PATH": "/opt/bundle/_internal", "PATH": "/usr/bin"}
    assert _scrub(env, frozen=True) == {"PATH": "/usr/bin"}


def test_frozen_empty_original_means_no_pre_launch_value():
    # PyInstaller sets LD_LIBRARY_PATH_ORIG="" when the variable was unset.
    env = {"LD_LIBRARY_PATH": "/opt/bundle/_internal", "LD_LIBRARY_PATH_ORIG": ""}
    assert _scrub(env, frozen=True) == {}


def test_scrub_never_mutates_its_input():
    env = {"LD_LIBRARY_PATH": "/opt/bundle/_internal", "LD_LIBRARY_PATH_ORIG": "/x"}
    snapshot = dict(env)
    _scrub(env, frozen=True)
    assert env == snapshot
