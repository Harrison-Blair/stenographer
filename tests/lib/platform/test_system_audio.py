# SPDX-License-Identifier: GPL-3.0-or-later
"""System audio capture contracts and platform wiring."""

from __future__ import annotations

import pytest

from stenographer.lib.platform.errors import UnsupportedPlatformError
from stenographer.lib.platform.linux.provider import LinuxPlatform
from stenographer.lib.platform.macos.provider import MacOSPlatform
from stenographer.lib.platform.platform import Platform
from stenographer.lib.platform.system_audio import SystemAudioCapture
from stenographer.lib.platform.windows.provider import WindowsPlatform


def test_linux_platform_provides_the_linux_system_audio_capture():
    capture = LinuxPlatform().system_audio_capture()

    assert isinstance(capture, SystemAudioCapture)
    assert capture.__class__.__name__ == "LinuxSystemAudioCapture"
    assert isinstance(LinuxPlatform(), Platform)


@pytest.mark.parametrize("provider", [MacOSPlatform(), WindowsPlatform()])
def test_non_linux_platforms_report_system_capture_as_unsupported(provider):
    with pytest.raises(UnsupportedPlatformError, match="system audio capture"):
        provider.system_audio_capture()
