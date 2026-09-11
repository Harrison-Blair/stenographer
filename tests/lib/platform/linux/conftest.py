# SPDX-License-Identifier: GPL-3.0-or-later
"""The Linux provider's unit tests only collect on Linux (evdev/fcntl/termios)."""

import sys

collect_ignore_glob = [] if sys.platform.startswith("linux") else ["*.py"]
