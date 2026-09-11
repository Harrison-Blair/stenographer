# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from enum import StrEnum


class Backend(StrEnum):
    LAYER_SHELL = "layer-shell"
    XWAYLAND = "xwayland"
