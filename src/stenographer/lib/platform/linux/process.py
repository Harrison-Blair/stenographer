# SPDX-License-Identifier: GPL-3.0-or-later
"""Environment for spawned helper processes (wl-copy/xclip, cue players, notify-send).

The PyInstaller onedir launcher exports ``LD_LIBRARY_PATH`` pointing into the
bundle's ``_internal/`` (which carries its own libwayland, libffi, ...). System
binaries spawned by the daemon must not inherit that or they load the bundled
libraries instead of the system ones. PyInstaller preserves the pre-launch
value in ``LD_LIBRARY_PATH_ORIG``; :func:`_scrub` is the pure unit target.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def _scrub(env: dict[str, str], frozen: bool) -> dict[str, str]:
    """Copy of *env* with the PyInstaller library injection undone. PURE."""
    env = dict(env)
    if not frozen:
        return env
    original = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if original:
        env["LD_LIBRARY_PATH"] = original
    else:
        env.pop("LD_LIBRARY_PATH", None)
    return env


def child_env() -> dict[str, str]:
    """The environment every spawned helper process should run with."""
    return _scrub(dict(os.environ), getattr(sys, "frozen", False))


def spawn_detached(argv: Sequence[str]) -> None:
    """Fire-and-forget a helper command: no pipes, own session, scrubbed env.

    ``OSError`` propagates — each caller owns its own failure policy.
    """
    subprocess.Popen(
        list(argv),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=child_env(),
    )
