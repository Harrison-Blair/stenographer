# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType

from stenographer.lib.contracts.loading_model import LoadingModel
from stenographer.lib.contracts.overlay_state import OverlayState

PILL_WIDTH = 187


PILL_HEIGHT = 43


EDGE_OFFSET = 32


LOADING_BORDER_COLOR = (0xF5, 0x9E, 0x0B)


LOADING_BORDER_WIDTH = 3


LOADING_BORDER_INSET = 1


LOADING_PULSE_SECONDS = 2.0


LOADING_OPACITY_MIN = 0.25


LOADING_OPACITY_MAX = 0.85


LOADING_ANIMATION_FPS = 60


LOADING_FRAME_INTERVAL = 1.0 / LOADING_ANIMATION_FPS


_CANVAS_MARGIN_LEFT = 8


_CANVAS_MARGIN_TOP = 5


_CANVAS_MARGIN_RIGHT = 9


_CANVAS_MARGIN_BOTTOM = 12


# The canvas sizes are multiples of 4, so that scales 1.25, 1.5, and 1.75 give
# whole buffer pixels and the compositor does not resample the pill.
CANVAS_WIDTH = _CANVAS_MARGIN_LEFT + PILL_WIDTH + _CANVAS_MARGIN_RIGHT


CANVAS_HEIGHT = _CANVAS_MARGIN_TOP + PILL_HEIGHT + _CANVAS_MARGIN_BOTTOM


_CORNER_RADIUS = 21


_ICON_SLOT_WIDTH = 29


_ICON_MAX_WIDTH = 25


_ICON_MAX_HEIGHT = 28


_CONTENT_INSET_LEFT = 8


_LABEL_GAP = 3


_DOT_DIAMETER = 5


_DOT_RIGHT_INSET = 12


_LABEL_FONT_SIZE = 18


_LABEL_WEIGHT = 600


_SPECTRUM_LEFT = 44


_SPECTRUM_BAR_WIDTH = 3


_SPECTRUM_BAR_GAP = 3


_SPECTRUM_MIN_HEIGHT = 3


_SPECTRUM_MAX_HEIGHT = 29


_SUPERSAMPLE = 4


_DYNAMIC_SUPERSAMPLE = 2


_PILL_FILL = (0x18, 0x18, 0x1C, 230)


_TEXT_FILL = (0xFF, 0xFF, 0xFF, 0xFF)


_SHADOW_ALPHA = 82


_SHADOW_BLUR = 4


_SHADOW_OFFSET_Y = 2


_ASSETS = Path(str(files("stenographer"))) / "assets"


_ICON_PATH = _ASSETS / "icons" / "stenographer.png"


_FONT_PATH = _ASSETS / "fonts" / "Caveat-wght.ttf"


STATE_LABELS: Mapping[OverlayState, str] = MappingProxyType(
    {
        OverlayState.TRANSCRIBING: "Transcribing",
        OverlayState.REFINING: "Refining",
        OverlayState.DELIVERING: "Delivering",
        OverlayState.CANCELLED: "Cancelled",
        OverlayState.ERROR: "Error",
        OverlayState.APPLIED: "Applied",
        OverlayState.SKIPPED: "Skipped",
        OverlayState.FALLBACK: "Fallback",
    }
)


STATE_DOT_COLORS: Mapping[OverlayState, tuple[int, int, int, int]] = MappingProxyType(
    {
        OverlayState.RECORDING: (0xEF, 0x44, 0x44, 0xFF),
        OverlayState.TRANSCRIBING: (0x3B, 0x82, 0xF6, 0xFF),
        OverlayState.REFINING: (0x14, 0xB8, 0xA6, 0xFF),
        OverlayState.DELIVERING: (0x8B, 0x5C, 0xF6, 0xFF),
        OverlayState.CANCELLED: (0xA1, 0xA1, 0xAA, 0xFF),
        OverlayState.ERROR: (0xEF, 0x44, 0x44, 0xFF),
        OverlayState.APPLIED: (0x22, 0xC5, 0x5E, 0xFF),
        OverlayState.SKIPPED: (0xA1, 0xA1, 0xAA, 0xFF),
        OverlayState.FALLBACK: (0xF5, 0x9E, 0x0B, 0xFF),
    }
)


LOADING_BORDER_COLORS: Mapping[LoadingModel, tuple[int, int, int]] = MappingProxyType(
    {
        LoadingModel.ASR: LOADING_BORDER_COLOR,
        LoadingModel.REFINE: STATE_DOT_COLORS[OverlayState.REFINING][:3],
    }
)
