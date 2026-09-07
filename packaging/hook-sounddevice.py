# SPDX-License-Identifier: GPL-3.0-or-later
"""Use system audio on Linux; retain wheel-provided PortAudio on other hosts."""

import sys

from PyInstaller.utils.hooks import collect_data_files

if sys.platform == "linux":
    excludedbinaries = ["libportaudio*", "libpipewire*", "libpulse*"]
else:
    datas = collect_data_files("_sounddevice_data")
