# SPDX-License-Identifier: GPL-3.0-or-later
"""Run host commands to completion through ``subprocess``."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence


class SubprocessCommandRunner:
    """Run a command without a shell; a command that cannot start exits 127."""

    def run(self, argv: Sequence[str]) -> int:
        try:
            return subprocess.run(list(argv), check=False).returncode
        except OSError:
            return 127

    def run_quiet(self, argv: Sequence[str]) -> int:
        try:
            return subprocess.run(
                list(argv), check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            ).returncode
        except OSError:
            return 127
