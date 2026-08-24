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


def pytest_ignore_collect(collection_path: pathlib.Path) -> bool | None:
    if collection_path.name.endswith("_smoke.py"):
        return os.environ.get("STENOGRAPHER_INTEGRATION") != "1"
    return None
