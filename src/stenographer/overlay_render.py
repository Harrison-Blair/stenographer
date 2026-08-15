# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic Pillow renderer for the metadata-only lifecycle overlay.

The renderer has no display, process, or audio dependencies.  It produces a
straight-alpha RGBA frame for either display backend and can pack that frame
as native ARGB32 when a compositor-facing buffer is required.
"""

from __future__ import annotations

import math
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from stenographer.status import OverlayState

PILL_WIDTH = 220
PILL_HEIGHT = 64
EDGE_OFFSET = 32

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

_SUPERSAMPLE = 4
_PILL_COLOR = (0x18, 0x18, 0x1B)
# Pillow's RGBA LANCZOS path filters premultiplied channels; the blue channel
# needs one high-resolution quantum so an interior output pixel lands on the
# requested straight-alpha #18181B after unpremultiplication.
_PILL_FILL = (*_PILL_COLOR[:2], _PILL_COLOR[2] + 1, 230)
_TEXT_FILL = (0xFF, 0xFF, 0xFF, 0xFF)
_SHADOW_FILL = (0, 0, 0, 82)
_SHADOW_BLUR = 6
_SHADOW_OFFSET_Y = 3

_ASSETS = Path(__file__).with_name("assets")
_ICON_PATH = _ASSETS / "icons" / "stenographer.png"
_FONT_PATH = _ASSETS / "fonts" / "Caveat-wght.ttf"

STATE_LABELS: Mapping[OverlayState, str] = MappingProxyType(
    {
        OverlayState.RECORDING: "Recording",
        OverlayState.MODEL_LOADING: "Loading model",
        OverlayState.TRANSCRIBING: "Transcribing",
        OverlayState.DELIVERING: "Delivering",
        OverlayState.ERROR: "Error",
    }
)

STATE_DOT_COLORS: Mapping[OverlayState, tuple[int, int, int, int]] = MappingProxyType(
    {
        OverlayState.RECORDING: (0xEF, 0x44, 0x44, 0xFF),
        OverlayState.MODEL_LOADING: (0xF5, 0x9E, 0x0B, 0xFF),
        OverlayState.TRANSCRIBING: (0x3B, 0x82, 0xF6, 0xFF),
        OverlayState.DELIVERING: (0x8B, 0x5C, 0xF6, 0xFF),
        OverlayState.ERROR: (0xEF, 0x44, 0x44, 0xFF),
    }
)


@dataclass(frozen=True, slots=True)
class OverlayFrame:
    """One scaled frame and the physical-pixel bounds of its visible pill."""

    image: Image.Image
    scale: float
    pill_bounds: tuple[int, int, int, int]

    @property
    def width(self) -> int:
        return self.image.width

    @property
    def height(self) -> int:
        return self.image.height

    @property
    def stride(self) -> int:
        return self.image.width * 4


def _scaled(logical_pixels: int, scale: float) -> int:
    return round(logical_pixels * scale)


def _crop_transparent(image: Image.Image) -> Image.Image:
    """Return the nontransparent bounds of an image without changing it."""
    rgba = image.convert("RGBA")
    bounds = rgba.getchannel("A").getbbox()
    if bounds is None:
        raise ValueError("overlay icon has no visible pixels")
    return rgba.crop(bounds)


@lru_cache(maxsize=1)
def _icon() -> Image.Image:
    with Image.open(_ICON_PATH) as source:
        return _crop_transparent(source)


def _font(size: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(_FONT_PATH, size=size)
    font.set_variation_by_axes([_LABEL_WEIGHT])
    return font


def _exclusive_box(bounds: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    left, top, right, bottom = bounds
    return left, top, right - 1, bottom - 1


def _render_high_resolution(
    state: OverlayState,
    target_size: tuple[int, int],
    pill_bounds: tuple[int, int, int, int],
    scale: float,
) -> Image.Image:
    factor = _SUPERSAMPLE
    high_size = tuple(value * factor for value in target_size)
    high_pill = tuple(value * factor for value in pill_bounds)
    high = Image.new("RGBA", high_size, (0, 0, 0, 0))

    shadow = Image.new("L", high_size, 0)
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_bounds = (
        high_pill[0],
        high_pill[1] + _scaled(_SHADOW_OFFSET_Y, scale) * factor,
        high_pill[2],
        high_pill[3] + _scaled(_SHADOW_OFFSET_Y, scale) * factor,
    )
    shadow_draw.rounded_rectangle(
        _exclusive_box(shadow_bounds),
        radius=_scaled(_CORNER_RADIUS, scale) * factor,
        fill=_SHADOW_FILL[3],
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=_scaled(_SHADOW_BLUR, scale) * factor))
    high.putalpha(shadow)

    draw = ImageDraw.Draw(high)
    draw.rounded_rectangle(
        _exclusive_box(high_pill),
        radius=_scaled(_CORNER_RADIUS, scale) * factor,
        fill=_PILL_FILL,
    )

    pill_left, pill_top, pill_right, pill_bottom = high_pill
    icon_slot_left = pill_left + _scaled(_CONTENT_INSET_LEFT, scale) * factor
    icon_slot_width = _scaled(_ICON_SLOT_WIDTH, scale) * factor
    max_icon_size = (
        _scaled(_ICON_MAX_WIDTH, scale) * factor,
        _scaled(_ICON_MAX_HEIGHT, scale) * factor,
    )
    icon = _icon().copy()
    icon.thumbnail(max_icon_size, Image.Resampling.LANCZOS)
    icon_x = icon_slot_left + (icon_slot_width - icon.width) // 2
    icon_y = pill_top + (pill_bottom - pill_top - icon.height) // 2
    high.alpha_composite(icon, (icon_x, icon_y))

    label_x = icon_slot_left + icon_slot_width + _scaled(_LABEL_GAP, scale) * factor
    label_center_y = (pill_top + pill_bottom) // 2
    label_font = _font(max(1, round(_LABEL_FONT_SIZE * scale * factor)))
    draw.text(
        (label_x, label_center_y),
        STATE_LABELS[state],
        font=label_font,
        fill=_TEXT_FILL,
        anchor="lm",
    )

    dot_center_x = pill_right - _scaled(_DOT_RIGHT_INSET, scale) * factor
    dot_center_y = label_center_y
    dot_radius = _scaled(_DOT_DIAMETER, scale) * factor // 2
    draw.ellipse(
        (
            dot_center_x - dot_radius,
            dot_center_y - dot_radius,
            dot_center_x + dot_radius - 1,
            dot_center_y + dot_radius - 1,
        ),
        fill=STATE_DOT_COLORS[state],
    )

    return high.resize(target_size, Image.Resampling.LANCZOS)


@lru_cache(maxsize=20)
def _cached_render(
    state: OverlayState, scale: float
) -> tuple[Image.Image, tuple[int, int, int, int]]:
    target_size = (_scaled(CANVAS_WIDTH, scale), _scaled(CANVAS_HEIGHT, scale))
    pill_bounds = (
        _scaled(_CANVAS_MARGIN_LEFT, scale),
        _scaled(_CANVAS_MARGIN_TOP, scale),
        _scaled(_CANVAS_MARGIN_LEFT + PILL_WIDTH, scale),
        _scaled(_CANVAS_MARGIN_TOP + PILL_HEIGHT, scale),
    )
    return _render_high_resolution(state, target_size, pill_bounds, scale), pill_bounds


def render_overlay(state: OverlayState, *, scale: float = 1.0) -> OverlayFrame:
    """Render a visible lifecycle state into a scale-aware RGBA canvas.

    ``hidden`` has no surface and is therefore deliberately not renderable.
    The returned image is a copy, so callers may safely hand it to backend
    conversion code without mutating the renderer's cache.
    """
    if not isinstance(state, OverlayState):
        raise TypeError("state must be an OverlayState")
    if state is OverlayState.HIDDEN:
        raise ValueError("hidden overlay state has no rendered surface")
    if isinstance(scale, bool) or not isinstance(scale, int | float):
        raise TypeError("scale must be a number")
    scale = float(scale)
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("scale must be finite and positive")
    image, pill_bounds = _cached_render(state, scale)
    return OverlayFrame(image.copy(), scale, pill_bounds)


def premultiplied_argb32(
    image: Image.Image,
    *,
    byteorder: Literal["little", "big"] = sys.byteorder,
) -> bytes:
    """Pack straight RGBA as premultiplied native 0xAARRGGBB pixels.

    On the supported little-endian Linux systems, the returned memory order is
    BGRA.  It is suitable for Wayland ``wl_shm`` ARGB8888 buffers and 32-bit
    ARGB X image uploads.
    """
    if byteorder not in {"little", "big"}:
        raise ValueError("byteorder must be little or big")
    source = image.convert("RGBA").tobytes()
    packed = bytearray(len(source))
    for offset in range(0, len(source), 4):
        red, green, blue, alpha = source[offset : offset + 4]
        premultiplied = (
            (red * alpha + 127) // 255,
            (green * alpha + 127) // 255,
            (blue * alpha + 127) // 255,
        )
        if byteorder == "little":
            packed[offset : offset + 4] = bytes(
                (premultiplied[2], premultiplied[1], premultiplied[0], alpha)
            )
        else:
            packed[offset : offset + 4] = bytes(
                (alpha, premultiplied[0], premultiplied[1], premultiplied[2])
            )
    return bytes(packed)


def overlay_position(
    output_rect: tuple[int, int, int, int],
    frame: OverlayFrame,
    *,
    edge_offset: float = EDGE_OFFSET,
) -> tuple[int, int]:
    """Place a frame so its visible pill is centered and offset from bottom."""
    if len(output_rect) != 4 or any(
        isinstance(value, bool) or not isinstance(value, int) for value in output_rect
    ):
        raise TypeError("output rectangle must contain four integers")
    output_x, output_y, output_width, output_height = output_rect
    pill_width = frame.pill_bounds[2] - frame.pill_bounds[0]
    pill_height = frame.pill_bounds[3] - frame.pill_bounds[1]
    physical_offset = round(edge_offset * frame.scale)
    if (
        output_width < pill_width
        or output_height < pill_height + physical_offset
        or edge_offset < 0
    ):
        raise ValueError("output is too small for the overlay placement")
    x = output_x + (output_width - frame.width) // 2
    y = output_y + output_height - physical_offset - frame.pill_bounds[3]
    return x, y
