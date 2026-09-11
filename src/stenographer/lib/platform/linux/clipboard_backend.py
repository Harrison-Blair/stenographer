# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import enum


class ClipboardBackend(enum.Enum):
    WL_COPY = "wl-copy"
    X11 = "x11"
