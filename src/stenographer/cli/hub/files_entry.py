# SPDX-License-Identifier: GPL-3.0-or-later
"""Describe one directory or audio file in the hub browser."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BrowserEntry:
    """One visible directory or audio file."""

    path: Path
    is_dir: bool
    duration_seconds: float | None
