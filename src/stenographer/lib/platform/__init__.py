# SPDX-License-Identifier: GPL-3.0-or-later
"""Platform selection: ``current_platform()`` returns the host's provider.

Stdlib-only and lazy: the concrete provider module is imported on first use,
so importing this package never drags in evdev, pywayland, or any other
OS-specific dependency. Always import from here or from
the individual protocol modules in ``stenographer.lib.platform``.
"""

from __future__ import annotations

import functools
import sys

from stenographer.lib.platform.errors import UnsupportedPlatformError
from stenographer.lib.platform.platform import Platform


@functools.cache
def current_platform() -> Platform:
    """The provider for the running host, constructed once per process."""
    if sys.platform.startswith("linux"):
        from stenographer.lib.platform.linux.provider import LinuxPlatform

        return LinuxPlatform()
    if sys.platform == "win32":
        from stenographer.lib.platform.windows.provider import WindowsPlatform

        return WindowsPlatform()
    if sys.platform == "darwin":
        from stenographer.lib.platform.macos.provider import MacOSPlatform

        return MacOSPlatform()
    raise UnsupportedPlatformError(f"unsupported platform: {sys.platform}")
