# SPDX-License-Identifier: GPL-3.0-or-later
"""Emit packaged native shell completion definitions."""

from __future__ import annotations

import sys
from importlib.resources import files

_ASSET_NAMES = {
    "bash": "stenographer.bash",
    "zsh": "_stenographer",
    "fish": "stenographer.fish",
}


def completion_definition(shell: str) -> str:
    """Return the static completion definition for ``shell``."""
    asset = files("stenographer").joinpath("assets", "completions", _ASSET_NAMES[shell])
    return asset.read_text(encoding="utf-8")


def cmd_completion(args) -> int:
    """Write one completion definition to stdout."""
    sys.stdout.write(completion_definition(args.shell))
    return 0
