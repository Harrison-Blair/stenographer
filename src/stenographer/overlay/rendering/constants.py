# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType

from stenographer.lib.contracts.overlay_state import OverlayState

PILL_WIDTH = 280


PILL_HEIGHT = 64


EDGE_OFFSET = 32


LOADING_BORDER_COLOR = (0xF5, 0x9E, 0x0B)


LOADING_BORDER_WIDTH = 4


LOADING_BORDER_INSET = 1


LOADING_PULSE_SECONDS = 2.0


LOADING_OPACITY_MIN = 0.25


LOADING_OPACITY_MAX = 0.85


LOADING_ANIMATION_FPS = 60


LOADING_FRAME_INTERVAL = 1.0 / LOADING_ANIMATION_FPS


_CANVAS_MARGIN_LEFT = 12


_CANVAS_MARGIN_TOP = 8


_CANVAS_MARGIN_RIGHT = 12


_CANVAS_MARGIN_BOTTOM = 16


CANVAS_WIDTH = _CANVAS_MARGIN_LEFT + PILL_WIDTH + _CANVAS_MARGIN_RIGHT


CANVAS_HEIGHT = _CANVAS_MARGIN_TOP + PILL_HEIGHT + _CANVAS_MARGIN_BOTTOM


_CORNER_RADIUS = 32


_ICON_SLOT_WIDTH = 44


_ICON_MAX_WIDTH = 38


_ICON_MAX_HEIGHT = 42


_CONTENT_INSET_LEFT = 12


_LABEL_GAP = 4


_DOT_DIAMETER = 8


_DOT_RIGHT_INSET = 18


_LABEL_FONT_SIZE = 22


_LABEL_WEIGHT = 600


_SPECTRUM_LEFT = 72


_SPECTRUM_BAR_WIDTH = 5


_SPECTRUM_BAR_GAP = 4


_SPECTRUM_MIN_HEIGHT = 4


_SPECTRUM_MAX_HEIGHT = 44


_SUPERSAMPLE = 4


_DYNAMIC_SUPERSAMPLE = 2


_PILL_COLOR = (0x18, 0x18, 0x1B)


_PILL_FILL = (*_PILL_COLOR[:2], _PILL_COLOR[2] + 1, 230)


_TEXT_FILL = (0xFF, 0xFF, 0xFF, 0xFF)


_SHADOW_FILL = (0, 0, 0, 82)


_SHADOW_BLUR = 6


_SHADOW_OFFSET_Y = 3


_ASSETS = Path(str(files("stenographer"))) / "assets"


_ICON_PATH = _ASSETS / "icons" / "stenographer.png"


_FONT_PATH = _ASSETS / "fonts" / "Caveat-wght.ttf"


STATE_LABELS: Mapping[OverlayState, str] = MappingProxyType(
    {
        OverlayState.TRANSCRIBING: "Transcribing",
        OverlayState.DELIVERING: "Delivering",
        OverlayState.ERROR: "Error",
    }
)


STATE_DOT_COLORS: Mapping[OverlayState, tuple[int, int, int, int]] = MappingProxyType(
    {
        OverlayState.RECORDING: (0xEF, 0x44, 0x44, 0xFF),
        OverlayState.TRANSCRIBING: (0x3B, 0x82, 0xF6, 0xFF),
        OverlayState.DELIVERING: (0x8B, 0x5C, 0xF6, 0xFF),
        OverlayState.ERROR: (0xEF, 0x44, 0x44, 0xFF),
    }
)
