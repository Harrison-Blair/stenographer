# SPDX-License-Identifier: GPL-3.0-or-later
"""The integration smoke suite is opt-in and never collected without the flag.

`*_smoke.py` modules import at module scope what they exercise for real (evdev,
uinput, pty/termios, the ASR model, Xlib). Skipping has to happen at collection
time so those imports never run in the unit suite; a marker-based skip would
already have imported the module.

The unit suite is also fenced off from the user's own directories: see
:func:`_isolate_host_directories`.
"""

from __future__ import annotations

import os
import pathlib

import pytest

#: Every environment variable the host providers consult when they resolve the
#: configuration file, the state directory, or the runtime directory --- see
#: ``lib/platform/linux/dirs.py`` and the macOS and Windows providers. All of
#: them take precedence over the home directory, so redirecting them is enough
#: to move every resolved path without touching ``HOME``. ``XDG_CACHE_HOME`` is
#: not read by this project but is honoured by huggingface_hub.
_HOST_DIRECTORY_VARS = (
    "XDG_CONFIG_HOME",
    "XDG_STATE_HOME",
    "XDG_CACHE_HOME",
    "XDG_RUNTIME_DIR",
    "APPDATA",
    "LOCALAPPDATA",
)


@pytest.fixture(autouse=True)
def _isolate_host_directories(request, monkeypatch, tmp_path_factory):
    """Point every host directory at a fresh temporary tree for unit tests.

    A unit test that reaches a real code path — ``stenographer transcribe``
    opening an analytics session, ``doctor`` naming a log, anything resolving
    the configuration path — otherwise writes into the user's own
    ``~/.local/state/stenographer`` and ``~/.config/stenographer``. That
    happened: file-sourced analytics rows from suite runs accumulated in the
    real database. Tests marked ``integration`` are exempt, because using the
    real host state is exactly what they are for.
    """

    if request.node.get_closest_marker("integration") is not None:
        return
    base = tmp_path_factory.mktemp("host")
    for name in _HOST_DIRECTORY_VARS:
        monkeypatch.setenv(name, str(base / name.casefold()))
    # An inherited override would defeat every redirect above.
    monkeypatch.delenv("STENOGRAPHER_CONFIG", raising=False)


@pytest.fixture
def drain_analytics():
    def drain(session):
        # Verify persistence independently of the daemon's two-second shutdown
        # budget, allowing for slow CI disks while retaining a bounded failure.
        assert session.close(timeout=15), session.health

    return drain


@pytest.fixture
def analytics_session(request, drain_analytics):
    from stenographer.lib.analytics.session import AnalyticsSession

    def create(path, **kwargs):
        session = AnalyticsSession(path, **kwargs)
        request.addfinalizer(lambda: drain_analytics(session))
        return session

    return create


def pytest_ignore_collect(collection_path: pathlib.Path) -> bool | None:
    if collection_path.name.endswith("_smoke.py"):
        return os.environ.get("STENOGRAPHER_INTEGRATION") != "1"
    return None
