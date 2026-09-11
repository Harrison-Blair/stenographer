# SPDX-License-Identifier: GPL-3.0-or-later
"""Observable result of saving a reviewed configuration."""

from __future__ import annotations

import pathlib
from dataclasses import dataclass


@dataclass(frozen=True)
class SaveResult:
    """The observable result of attempting to persist a reviewed config."""

    changed: bool
    path: pathlib.Path
    backup_path: pathlib.Path | None = None
