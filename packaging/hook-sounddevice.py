# SPDX-License-Identifier: GPL-3.0-or-later
# PyInstaller hook: prevent bundling of build-machine audio libraries.
# The target system MUST provide these at runtime (see spec/10-packaging.md).
excludedbinaries = ["libportaudio*", "libpipewire*", "libpulse*"]
