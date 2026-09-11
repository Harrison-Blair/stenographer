# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for process._scrub: the PyInstaller LD_LIBRARY_PATH undo."""

from __future__ import annotations

from stenographer.lib.platform.linux.process import _scrub


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


def test_spawn_detached_starts_a_real_child_in_its_own_session(tmp_path):
    """Fire-and-forget: no pipes, own session, and the caller never waits.

    The child is a real Python process that records its session id, which must
    differ from this test runner's — a helper left in the daemon's session dies
    with the daemon's controlling terminal.
    """
    import contextlib
    import os
    import sys
    import time

    import psutil

    from stenographer.lib.platform.linux.process import spawn_detached

    marker = tmp_path / "session.txt"
    marker.touch()
    spawn_detached(
        [
            sys.executable,
            "-c",
            "import os, sys; from pathlib import Path; "
            "Path(sys.argv[1]).write_text(f'{os.getsid(0)} {os.getpid()}')",
            str(marker),
        ]
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not marker.read_text().strip():
        time.sleep(0.01)
    recorded = marker.read_text().strip()
    assert recorded, "the detached child never recorded its session id"

    session_id, child_pid = (int(field) for field in recorded.split())
    assert session_id != os.getsid(0)

    # Let the child finish exiting before the test returns, so nothing it does
    # on the way out runs alongside the rest of the suite.
    while time.monotonic() < deadline:
        with contextlib.suppress(psutil.Error):
            if psutil.Process(child_pid).status() != psutil.STATUS_ZOMBIE:
                time.sleep(0.01)
                continue
        break


def test_spawn_detached_lets_an_unrunnable_command_fail_loudly():
    # OSError propagates: each caller owns its own failure policy (the
    # notifier swallows it; a cue player reports it).
    import pytest

    from stenographer.lib.platform.linux.process import spawn_detached

    with pytest.raises(OSError):
        spawn_detached(["stenographer-definitely-not-a-real-binary"])
