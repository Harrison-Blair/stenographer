# SPDX-License-Identifier: GPL-3.0-or-later
# PyInstaller runtime hook: ensure the system's libportaudio is findable
# by ctypes when running inside a frozen bundle.  See spec/10-packaging.md:
# libportaudio2 is a required system dependency and MUST NOT be bundled.

import os
import sys


def _add_system_lib_paths() -> None:
    if not getattr(sys, "frozen", False):
        return
    extra = []
    for candidate in (
        "/usr/lib",
        "/usr/lib64",
        "/lib",
        "/lib64",
        "/usr/lib/x86_64-linux-gnu",
        "/lib/x86_64-linux-gnu",
        "/usr/lib/aarch64-linux-gnu",
    ):
        if os.path.isdir(candidate):
            extra.append(candidate)
    if not extra:
        return
    existing = os.environ.get("LD_LIBRARY_PATH", "")
    if existing:
        existing = ":" + existing
    os.environ["LD_LIBRARY_PATH"] = ":".join(extra) + existing


_add_system_lib_paths()
