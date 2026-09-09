# SPDX-License-Identifier: GPL-3.0-or-later
"""The integration smoke suite is opt-in and never collected without the flag.

`*_smoke.py` modules import at module scope what they exercise for real (evdev,
uinput, pty/termios, the ASR model, Xlib). Skipping has to happen at collection
time so those imports never run in the unit suite; a marker-based skip would
already have imported the module.
"""

from __future__ import annotations

import os
import pathlib

import pytest


@pytest.fixture
def drain_analytics():
    def drain(session):
        # Verify persistence independently of the daemon's two-second shutdown
        # budget, allowing for slow CI disks while retaining a bounded failure.
        assert session.close(timeout=15), session.health

    return drain


@pytest.fixture
def analytics_session(request, drain_analytics):
    from stenographer.analytics import AnalyticsSession

    def create(path, **kwargs):
        session = AnalyticsSession(path, **kwargs)
        request.addfinalizer(lambda: drain_analytics(session))
        return session

    return create


def pytest_ignore_collect(collection_path: pathlib.Path) -> bool | None:
    if collection_path.name.endswith("_smoke.py"):
        return os.environ.get("STENOGRAPHER_INTEGRATION") != "1"
    return None
