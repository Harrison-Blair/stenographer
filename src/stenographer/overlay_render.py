# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic Pillow renderer for the isolated lifecycle overlay.

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

from stenographer.status import SPECTRUM_BANDS, OverlayState

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


@lru_cache(maxsize=8)
def _font(size: int) -> ImageFont.FreeTypeFont:
    """Parse the variable label font once per size.

    The returned instance is shared across renders: callers must treat it as
    immutable and never re-set variation axes on it.
    """
    font = ImageFont.truetype(_FONT_PATH, size=size)
    font.set_variation_by_axes([_LABEL_WEIGHT])
    return font


def _exclusive_box(bounds: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    left, top, right, bottom = bounds
    return left, top, right - 1, bottom - 1


def _validated_levels(levels: object | None) -> tuple[int, ...]:
    if levels is None:
        return (0,) * SPECTRUM_BANDS
    if not isinstance(levels, tuple | list) or len(levels) != SPECTRUM_BANDS:
        raise ValueError(f"recording spectrum requires {SPECTRUM_BANDS} levels")
    if any(
        not isinstance(level, int) or isinstance(level, bool) or not 0 <= level <= 255
        for level in levels
    ):
        raise ValueError("recording spectrum levels must be integers from 0 to 255")
    return tuple(levels)


def loading_border_opacity(elapsed_seconds: object) -> float:
    """Return the 60 fps, two-second sinusoidal loading-border opacity."""
    if isinstance(elapsed_seconds, bool) or not isinstance(elapsed_seconds, int | float):
        raise TypeError("loading elapsed time must be a number")
    elapsed = float(elapsed_seconds)
    if not math.isfinite(elapsed) or elapsed < 0:
        raise ValueError("loading elapsed time must be finite and non-negative")
    frame_elapsed = math.floor(elapsed * LOADING_ANIMATION_FPS) / LOADING_ANIMATION_FPS
    phase = (frame_elapsed % LOADING_PULSE_SECONDS) / LOADING_PULSE_SECONDS
    midpoint = (LOADING_OPACITY_MIN + LOADING_OPACITY_MAX) / 2.0
    amplitude = (LOADING_OPACITY_MAX - LOADING_OPACITY_MIN) / 2.0
    opacity = midpoint - amplitude * math.cos(math.tau * phase)
    return min(LOADING_OPACITY_MAX, max(LOADING_OPACITY_MIN, opacity))


@dataclass(slots=True)
class LoadingPulse:
    """Pure loading-pulse edge, elapsed, and frame-deadline math. PURE.

    The class never reads a clock.  Backends stay the owners of deadline
    lifecycle policy: when to arm the frame cadence, and when destroying or
    recreating a surface clears (or deliberately preserves) the deadline.
    """

    active: bool = False
    started_at: float | None = None
    next_frame_at: float | None = None

    def set_active(self, active: bool, now: float) -> bool:
        """Apply one activity edge; return False for a duplicate edge."""
        if active == self.active:
            return False
        self.active = active
        self.started_at = now if active else None
        self.next_frame_at = None
        return True

    def elapsed(self, now: float) -> float | None:
        """Return the animation-driving elapsed time, or None while inactive."""
        if not self.active or self.started_at is None:
            return None
        return max(0.0, now - self.started_at)

    def timeout(self, now: float, visible: bool) -> float | None:
        """Return the wait until the next armed frame, or None when idle."""
        if not self.active or not visible or self.next_frame_at is None:
            return None
        return max(0.0, self.next_frame_at - now)

    def frame_due(self, now: float, visible: bool) -> bool:
        """Return whether an armed frame deadline has been reached."""
        timeout = self.timeout(now, visible)
        return timeout is not None and timeout <= 0.0

    def advance(self, now: float) -> None:
        """Re-arm one fixed frame interval after a due frame was drawn."""
        self.next_frame_at = now + LOADING_FRAME_INTERVAL

    def arm(self, now: float) -> None:
        """Start (or restart) the frame cadence from ``now``."""
        self.advance(now)

    def disarm_frames(self) -> None:
        """Clear the frame deadline without touching activity or start time."""
        self.next_frame_at = None


def spectrum_bar_bounds(
    levels: object | None,
    *,
    pill_bounds: tuple[int, int, int, int] = (
        _CANVAS_MARGIN_LEFT,
        _CANVAS_MARGIN_TOP,
        _CANVAS_MARGIN_LEFT + PILL_WIDTH,
        _CANVAS_MARGIN_TOP + PILL_HEIGHT,
    ),
    scale: float = 1.0,
) -> tuple[tuple[int, int, int, int], ...]:
    """Return deterministic exclusive pixel bounds for exactly 18 bars."""
    values = _validated_levels(levels)
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("scale must be finite and positive")
    center_y = (pill_bounds[1] + pill_bounds[3]) // 2
    left = pill_bounds[0] + _scaled(_SPECTRUM_LEFT, scale)
    width = max(1, _scaled(_SPECTRUM_BAR_WIDTH, scale))
    step = width + _scaled(_SPECTRUM_BAR_GAP, scale)
    bounds = []
    for index, level in enumerate(values):
        logical_height = _SPECTRUM_MIN_HEIGHT + (
            (_SPECTRUM_MAX_HEIGHT - _SPECTRUM_MIN_HEIGHT) * level / 255.0
        )
        height = max(1, _scaled(round(logical_height), scale))
        top = center_y - height // 2
        x = left + index * step
        bounds.append((x, top, x + width, top + height))
    return tuple(bounds)


def _frame_geometry(scale: float) -> tuple[tuple[int, int], tuple[int, int, int, int]]:
    target_size = (_scaled(CANVAS_WIDTH, scale), _scaled(CANVAS_HEIGHT, scale))
    pill_left = (CANVAS_WIDTH - PILL_WIDTH) // 2
    pill_bounds = (
        _scaled(pill_left, scale),
        _scaled(_CANVAS_MARGIN_TOP, scale),
        _scaled(pill_left + PILL_WIDTH, scale),
        _scaled(_CANVAS_MARGIN_TOP + PILL_HEIGHT, scale),
    )
    return target_size, pill_bounds


def _render_static_high_resolution(
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

    label_center_y = (pill_top + pill_bottom) // 2
    if state is not OverlayState.RECORDING:
        label_x = icon_slot_left + icon_slot_width + _scaled(_LABEL_GAP, scale) * factor
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


@lru_cache(maxsize=24)
def _cached_static_render(
    state: OverlayState,
    scale: float,
) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """Cache the fully static frame (shadow, pill, icon, label, dot) per state.

    Callers must NEVER draw on the returned image — it is the shared cached
    instance.  Copy it before compositing anything dynamic on top.
    """
    target_size, pill_bounds = _frame_geometry(scale)
    image = _render_static_high_resolution(state, target_size, pill_bounds, scale)
    return image, pill_bounds


def _render_dynamic_layer(
    levels: tuple[int, ...],
    pill_bounds: tuple[int, int, int, int],
    scale: float,
    loading_alpha: int | None,
) -> Image.Image:
    factor = _DYNAMIC_SUPERSAMPLE
    pill_size = (pill_bounds[2] - pill_bounds[0], pill_bounds[3] - pill_bounds[1])
    high_size = tuple(value * factor for value in pill_size)
    high_pill = (0, 0, *high_size)
    high = Image.new("RGBA", high_size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(high)

    if loading_alpha is not None:
        inset = _scaled(LOADING_BORDER_INSET, scale) * factor
        border_bounds = (
            high_pill[0] + inset,
            high_pill[1] + inset,
            high_pill[2] - inset,
            high_pill[3] - inset,
        )
        draw.rounded_rectangle(
            _exclusive_box(border_bounds),
            radius=max(1, (_scaled(_CORNER_RADIUS, scale) * factor) - inset),
            outline=(*LOADING_BORDER_COLOR, loading_alpha),
            width=max(1, _scaled(LOADING_BORDER_WIDTH, scale) * factor),
        )

    if levels:
        for bounds in spectrum_bar_bounds(
            levels,
            pill_bounds=high_pill,
            scale=scale * factor,
        ):
            draw.rounded_rectangle(
                _exclusive_box(bounds),
                radius=max(1, (bounds[2] - bounds[0]) // 2),
                fill=_TEXT_FILL,
            )

    return high.resize(pill_size, Image.Resampling.LANCZOS)


def render_overlay(
    state: OverlayState,
    *,
    scale: float = 1.0,
    levels: object | None = None,
    loading_elapsed: object | None = None,
) -> OverlayFrame:
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
    if state is not OverlayState.RECORDING and levels is not None:
        raise ValueError("spectrum levels apply only to the recording state")
    normalized_levels = _validated_levels(levels) if state is OverlayState.RECORDING else ()
    loading_alpha = (
        None if loading_elapsed is None else round(loading_border_opacity(loading_elapsed) * 255)
    )
    static, pill_bounds = _cached_static_render(state, scale)
    if normalized_levels or loading_alpha is not None:
        dynamic = _render_dynamic_layer(
            normalized_levels,
            pill_bounds,
            scale,
            loading_alpha,
        )
        image = static.copy()
        image.alpha_composite(dynamic, (pill_bounds[0], pill_bounds[1]))
    else:
        image = static.copy()
    return OverlayFrame(image, scale, pill_bounds)


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
    premultiplied = image.convert("RGBa")
    if byteorder == "little":
        return premultiplied.tobytes("raw", "BGRa")
    red, green, blue, alpha = premultiplied.split()
    return Image.merge("RGBA", (alpha, red, green, blue)).tobytes()


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
