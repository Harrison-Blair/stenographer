# SPDX-License-Identifier: GPL-3.0-or-later
"""Facts about a diagnostic log file."""

from __future__ import annotations

import pathlib
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LogStatus:
    """One log file as the report sees it.

    The three states a report must tell apart: ``size is None`` means the file
    does not exist, ``readable=False`` means it exists but this user may not
    open it (a daemon once started under another account leaves exactly that),
    and otherwise ``tail`` holds its recent complaints.
    """

    name: str
    path: pathlib.Path
    size: int | None
    tail: tuple[str, ...] = ()
    readable: bool = True
