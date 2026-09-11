# SPDX-License-Identifier: GPL-3.0-or-later
import functools
import sys

from stenographer.lib.platform.errors import UnsupportedPlatformError
from stenographer.overlay.platform.provider import OverlayPlatform


@functools.cache
def current_platform() -> OverlayPlatform:
    if sys.platform.startswith("linux"):
        from .linux.provider import LinuxOverlayPlatform

        return LinuxOverlayPlatform()
    if sys.platform == "win32":
        from .windows.provider import WindowsOverlayPlatform

        return WindowsOverlayPlatform()
    if sys.platform == "darwin":
        from .macos.provider import MacOSOverlayPlatform

        return MacOSOverlayPlatform()
    raise UnsupportedPlatformError(f"unsupported platform: {sys.platform}")
