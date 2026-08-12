# SPDX-License-Identifier: GPL-3.0-or-later
"""Pillow software renderer for the status HUD frame.

The renderer draws the whole overlay frame (RGBA, straight alpha) so both the
Wayland and X11 backends can stay dumb byte-pushers. Layout mirrors the old
GTK box model exactly (padding, icon size, spectrum geometry) so the HUD looks
identical to the retired GTK helper. Static chrome (shadow, rounded box,
border, icon) is rendered once at 4x and downscaled with LANCZOS because
``ImageDraw`` shapes are not antialiased; each frame is then a cheap copy plus
text and spectrum bars.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# Preview geometry (moved verbatim from overlay_app so the renderer owns it).
_PREVIEW_WIDTH_CHARS = 42
_PREVIEW_ROWS = 2
_PREVIEW_RECENT_CHARS = 96
_PREVIEW_HEIGHT_PX = 34

# Box model, mirroring the retired GTK CSS (padding 12/18/14/18, etc.).
_PADDING_TOP = 12
_PADDING_RIGHT = 18
_PADDING_BOTTOM = 14
_PADDING_LEFT = 18
_ICON_SIZE = 76
_BOX_SPACING = 14
_CONTENT_SPACING = 4
_HEADER_SPACING = 8
_SPECTRUM_WIDTH = 280
_SPECTRUM_HEIGHT = 54
_CORNER_RADIUS = 20

# Shadow / supersampling for the static chrome.
_SHADOW_BLUR = 14
_SHADOW_OFFSET_Y = 8
_SHADOW_MARGIN = 32
_SHADOW_MARGIN_BOTTOM = 36
_SUPERSAMPLE = 4

# Colours (RGBA), matching the GTK CSS values.
_BOX_FILL = (45, 45, 48, 209)  # rgba(45, 45, 48, 0.82)
_BOX_BORDER = (255, 255, 255, 51)  # rgba(255, 255, 255, 0.20)
_SHADOW_FILL = (0, 0, 0, 92)  # rgba(0, 0, 0, 0.36)
_STATUS_COLOR = (242, 242, 242, 255)  # #f2f2f2
_VERSION_COLOR = (242, 242, 242, 102)  # #f2f2f2 @ 40%
_PREVIEW_STABLE_COLOR = (247, 247, 247, 235)
_PREVIEW_PROVISIONAL_COLOR = (242, 242, 242, 148)

# Spectrum bar geometry (identical maths to the old _draw_spectrum).
_BAR_FILL = (255, 255, 255, 173)  # rgba(1, 1, 1, 0.68)
_BAR_GAP = 5.0
_BAR_BASELINE_INSET = 8.0
_BAR_MIN_WIDTH = 3.0
_BAR_MIN_HEIGHT = 2.0

# Font sizes (px).
_STATUS_FONT_SIZE = 20
_VERSION_FONT_SIZE = 11
_PREVIEW_FONT_SIZE = 12
_STATUS_WEIGHT = 600


def _trim_preview(
    stable: str,
    provisional: str,
    limit: int = _PREVIEW_RECENT_CHARS,
) -> tuple[str, str]:
    """Keep the newest preview text and preserve its stable/tail boundary."""
    combined = stable + provisional
    if len(combined) <= limit:
        return stable, provisional
    target = len(combined) - limit
    boundary = next(
        (index + 1 for index in range(target, len(combined)) if combined[index].isspace()),
        target,
    )
    if boundary < len(stable):
        return "…" + stable[boundary:], provisional
    return "", "…" + provisional[max(0, boundary - len(stable)) :]


def _wrap_segments(
    stable: str,
    provisional: str,
    max_width_px: float,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_lines: int = _PREVIEW_ROWS,
) -> list[list[tuple[str, bool]]]:
    """Greedily word-wrap the preview, keeping the stable/provisional boundary.

    Returns up to ``max_lines`` lines; each line is a list of ``(text,
    is_provisional)`` runs so the caller can colour the stable prefix and the
    revisable tail differently. Overflow past ``max_lines`` is truncated with a
    trailing ``"…"``.
    """
    combined = stable + provisional
    boundary = len(stable)
    words: list[tuple[int, int]] = []
    index = 0
    length = len(combined)
    while index < length:
        if combined[index].isspace():
            index += 1
            continue
        start = index
        while index < length and not combined[index].isspace():
            index += 1
        words.append((start, index))

    lines: list[list[tuple[int, int]]] = []
    current: list[tuple[int, int]] = []
    for word in words:
        trial = [*current, word]
        text = " ".join(combined[a:b] for a, b in trial)
        if current and font.getlength(text) > max_width_px:
            lines.append(current)
            current = [word]
        else:
            current = trial
    if current:
        lines.append(current)

    truncated = len(lines) > max_lines
    kept = lines[:max_lines]
    result: list[list[tuple[str, bool]]] = []
    for line_index, line in enumerate(kept):
        runs = _line_to_runs(combined, boundary, line)
        if truncated and line_index == max_lines - 1:
            runs = _append_ellipsis(runs)
        result.append(runs)
    return result


def _line_to_runs(
    combined: str,
    boundary: int,
    words: list[tuple[int, int]],
) -> list[tuple[str, bool]]:
    """Flatten one wrapped line into coalesced stable/provisional runs."""
    runs: list[tuple[str, bool]] = []

    def push(char: str, provisional: bool) -> None:
        if runs and runs[-1][1] == provisional:
            runs[-1] = (runs[-1][0] + char, provisional)
        else:
            runs.append((char, provisional))

    for order, (start, end) in enumerate(words):
        if order > 0:
            push(" ", start >= boundary)
        for position in range(start, end):
            push(combined[position], position >= boundary)
    return runs


def _append_ellipsis(runs: list[tuple[str, bool]]) -> list[tuple[str, bool]]:
    """Append a truncation ellipsis, extending the trailing run's style."""
    if runs and runs[-1][1]:
        runs[-1] = (runs[-1][0] + "…", True)
    else:
        runs.append(("…", False))
    return runs


def to_premultiplied_bgra(img: Image.Image) -> bytes:
    """Return premultiplied little-endian BGRA bytes for a straight-alpha frame.

    Both Wayland ``ARGB8888`` shm buffers and composited 32-bit X windows read
    premultiplied BGRA in little-endian memory order, so both backends share
    this converter.
    """
    rgba = np.asarray(img.convert("RGBA"), dtype=np.uint16)
    alpha = rgba[..., 3:4]
    premultiplied = (rgba[..., :3] * alpha + 127) // 255
    out = np.empty(rgba.shape, dtype=np.uint8)
    out[..., 0] = premultiplied[..., 2]  # B
    out[..., 1] = premultiplied[..., 1]  # G
    out[..., 2] = premultiplied[..., 0]  # R
    out[..., 3] = rgba[..., 3]  # A
    return out.tobytes()


def _load_status_font(
    font_path: str | None, size: int
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load the Caveat status font, guarding the variable-weight axis."""
    if not font_path:
        return ImageFont.load_default(size)
    try:
        font = ImageFont.truetype(font_path, size)
    except OSError:
        return ImageFont.load_default(size)
    with contextlib.suppress(OSError, NotImplementedError):
        font.set_variation_by_axes([_STATUS_WEIGHT])
    return font


def _load_sans_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load the bundled DejaVuSans sans font used for version and preview."""
    sans_path = os.environ.get("STENOGRAPHER_SANS_FONT_PATH")
    if not sans_path:
        sans_path = str(
            Path(__file__).resolve().parent.parent / "assets" / "fonts" / "DejaVuSans.ttf"
        )
    try:
        return ImageFont.truetype(sans_path, size)
    except OSError:
        return ImageFont.load_default(size)


def _line_height(font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> int:
    """Return the font's ascent + descent line height."""
    ascent, descent = font.getmetrics()
    return ascent + descent


class HudRenderer:
    """Render the full HUD frame with Pillow.

    ``scale`` is an integer buffer scale (HiDPI); every geometry constant and
    font size is multiplied by it, and the static chrome is rebuilt to match.
    """

    def __init__(
        self,
        band_count: int,
        version: str,
        icon_path: str | None,
        font_path: str | None,
        scale: int = 1,
    ) -> None:
        self._band_count = max(1, int(band_count))
        self._version = version
        self._icon_path = icon_path
        self._scale = max(1, int(scale))
        self._status_font = _load_status_font(font_path, self._px(_STATUS_FONT_SIZE))
        self._version_font = _load_sans_font(self._px(_VERSION_FONT_SIZE))
        self._preview_font = _load_sans_font(self._px(_PREVIEW_FONT_SIZE))
        self._layout()
        self._chrome = self._build_chrome()

    def _px(self, value: float) -> int:
        return round(value * self._scale)

    def _layout(self) -> None:
        pad_t = self._px(_PADDING_TOP)
        pad_r = self._px(_PADDING_RIGHT)
        pad_b = self._px(_PADDING_BOTTOM)
        pad_l = self._px(_PADDING_LEFT)
        icon = self._px(_ICON_SIZE)
        box_spacing = self._px(_BOX_SPACING)
        content_spacing = self._px(_CONTENT_SPACING)
        content_w = self._px(_SPECTRUM_WIDTH)
        spectrum_h = self._px(_SPECTRUM_HEIGHT)
        preview_h = self._px(_PREVIEW_HEIGHT_PX)
        header_h = max(_line_height(self._status_font), _line_height(self._version_font))

        content_h = header_h + content_spacing + preview_h + content_spacing + spectrum_h
        box_content_h = max(icon, content_h)
        box_w = pad_l + icon + box_spacing + content_w + pad_r
        box_h = pad_t + box_content_h + pad_b

        margin = self._px(_SHADOW_MARGIN)
        margin_bottom = self._px(_SHADOW_MARGIN_BOTTOM)
        box_x = margin
        box_y = margin
        self._canvas_size = (box_w + 2 * margin, box_h + margin + margin_bottom)
        self._box_rect = (box_x, box_y, box_x + box_w, box_y + box_h)

        self._icon_size = icon
        self._icon_pos = (box_x + pad_l, box_y + pad_t + (box_content_h - icon) // 2)

        content_x = box_x + pad_l + icon + box_spacing
        content_y = box_y + pad_t + (box_content_h - content_h) // 2
        self._content_width = content_w
        self._header_pos = (content_x, content_y)
        self._version_right = content_x + content_w
        preview_y = content_y + header_h + content_spacing
        self._preview_pos = (content_x, preview_y)
        self._preview_line_height = _line_height(self._preview_font)
        spectrum_y = preview_y + preview_h + content_spacing
        self._spectrum_rect = (content_x, spectrum_y, content_w, spectrum_h)

    def _build_chrome(self) -> Image.Image:
        supersample = _SUPERSAMPLE
        width, height = self._canvas_size
        big = (width * supersample, height * supersample)
        radius = self._px(_CORNER_RADIUS) * supersample
        box = tuple(coordinate * supersample for coordinate in self._box_rect)

        shadow = Image.new("RGBA", big, (0, 0, 0, 0))
        offset = self._px(_SHADOW_OFFSET_Y) * supersample
        ImageDraw.Draw(shadow).rounded_rectangle(
            (box[0], box[1] + offset, box[2], box[3] + offset),
            radius=radius,
            fill=_SHADOW_FILL,
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(_SHADOW_BLUR * self._scale * supersample))

        box_layer = Image.new("RGBA", big, (0, 0, 0, 0))
        draw = ImageDraw.Draw(box_layer)
        draw.rounded_rectangle(box, radius=radius, fill=_BOX_FILL)
        draw.rounded_rectangle(
            box,
            radius=radius,
            outline=_BOX_BORDER,
            width=max(1, self._scale) * supersample,
        )

        chrome_big = Image.alpha_composite(shadow, box_layer)
        chrome = chrome_big.resize(self._canvas_size, Image.LANCZOS)

        if self._icon_path:
            try:
                icon = Image.open(self._icon_path).convert("RGBA")
            except OSError:
                icon = None
            if icon is not None:
                icon = icon.resize((self._icon_size, self._icon_size), Image.LANCZOS)
                overlay = Image.new("RGBA", self._canvas_size, (0, 0, 0, 0))
                overlay.paste(icon, self._icon_pos)
                chrome = Image.alpha_composite(chrome, overlay)
        return chrome

    @property
    def size(self) -> tuple[int, int]:
        """Canvas size (width, height) in pixels, including shadow margins."""
        return self._canvas_size

    def render(
        self,
        label: str,
        preview: tuple[str, str] = ("", ""),
        levels: list[float] | None = None,
    ) -> Image.Image:
        """Render one full HUD frame as a straight-alpha RGBA image."""
        frame = self._chrome.copy()
        draw = ImageDraw.Draw(frame)
        self._draw_header(draw, label)
        self._draw_preview(draw, preview)
        self._draw_spectrum(draw, levels or [])
        return frame

    def _draw_header(self, draw: ImageDraw.ImageDraw, label: str) -> None:
        header_x, header_y = self._header_pos
        draw.text((header_x, header_y), label, font=self._status_font, fill=_STATUS_COLOR)
        draw.text(
            (self._version_right, header_y),
            self._version,
            font=self._version_font,
            fill=_VERSION_COLOR,
            anchor="ra",
        )

    def _draw_preview(self, draw: ImageDraw.ImageDraw, preview: tuple[str, str]) -> None:
        stable, provisional = _trim_preview(preview[0], preview[1])
        if not stable and not provisional:
            return
        lines = _wrap_segments(stable, provisional, self._content_width, self._preview_font)
        preview_x, preview_y = self._preview_pos
        for line in lines:
            cursor = preview_x
            for text, provisional_run in line:
                color = _PREVIEW_PROVISIONAL_COLOR if provisional_run else _PREVIEW_STABLE_COLOR
                draw.text((cursor, preview_y), text, font=self._preview_font, fill=color)
                cursor += self._preview_font.getlength(text)
            preview_y += self._preview_line_height

    def _draw_spectrum(self, draw: ImageDraw.ImageDraw, levels: list[float]) -> None:
        origin_x, origin_y, width, height = self._spectrum_rect
        count = self._band_count
        gap = _BAR_GAP * self._scale
        baseline = max(_BAR_MIN_HEIGHT * self._scale, height - _BAR_BASELINE_INSET * self._scale)
        bar_width = max(_BAR_MIN_WIDTH * self._scale, (width - gap * (count - 1)) / count)
        for index in range(count):
            level = float(levels[index]) if index < len(levels) else 0.0
            level = min(1.0, max(0.0, level))
            x = origin_x + index * (bar_width + gap)
            fill_height = max(_BAR_MIN_HEIGHT * self._scale, level * baseline)
            top = origin_y + baseline - fill_height
            draw.rectangle((x, top, x + bar_width, origin_y + baseline), fill=_BAR_FILL)
