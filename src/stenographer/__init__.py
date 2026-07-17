# SPDX-License-Identifier: GPL-3.0-or-later
"""stenographer: local, offline, Wayland push-to-talk / toggle dictation.

The version is read from the installed package metadata (which is
populated from ``pyproject.toml`` ``[project].version``). This keeps
``pyproject.toml`` as the single source of truth.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("stenographer")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"
