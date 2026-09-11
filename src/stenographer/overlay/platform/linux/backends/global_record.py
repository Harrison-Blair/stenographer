# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _Global:
    name: int
    interface: str
    version: int
