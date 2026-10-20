# SPDX-License-Identifier: GPL-3.0-or-later
"""System audio capture contracts and platform wiring."""

from __future__ import annotations

from stenographer.lib.platform.linux.provider import LinuxPlatform
from stenographer.lib.platform.platform import Platform
from stenographer.lib.platform.system_audio import SystemAudioCapture


def test_linux_platform_provides_the_linux_system_audio_capture():
    capture = LinuxPlatform().system_audio_capture()

    assert isinstance(capture, SystemAudioCapture)
    assert capture.__class__.__name__ == "LinuxSystemAudioCapture"
    assert isinstance(LinuxPlatform(), Platform)
