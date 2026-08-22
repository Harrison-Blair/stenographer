# SPDX-License-Identifier: GPL-3.0-or-later
"""Platform selection: ``current_platform()`` returns the host's provider.

Stdlib-only and lazy: the concrete provider module is imported on first use,
so importing this package never drags in evdev, pywayland, or any other
OS-specific dependency. Always import from here or from
``stenographer.platform.base``; never ``from stenographer import platform``.
"""

from __future__ import annotations

import functools
import sys

from stenographer.platform.base import Platform, UnsupportedPlatformError

__all__ = ["Platform", "UnsupportedPlatformError", "current_platform"]


@functools.cache
def current_platform() -> Platform:
    """The provider for the running host, constructed once per process."""
    if sys.platform.startswith("linux"):
        from stenographer.platform.linux import LinuxPlatform

        return LinuxPlatform()
    if sys.platform == "win32":
        from stenographer.platform.windows import WindowsPlatform

        return WindowsPlatform()
    raise UnsupportedPlatformError(f"unsupported platform: {sys.platform}")
