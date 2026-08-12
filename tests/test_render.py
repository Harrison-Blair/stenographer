# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the Pillow software renderer (`visualizer/render.py`)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from stenographer.visualizer.render import (
    HudRenderer,
    _load_sans_font,
    _wrap_segments,
    to_premultiplied_bgra,
)

_ASSETS = Path(__file__).resolve().parent.parent / "src" / "stenographer" / "assets" / "fonts"
_CAVEAT_PATH = str(_ASSETS / "Caveat-wght.ttf")
_BAR_FILL = (255, 255, 255, 173)


def _renderer(band_count: int = 16, font_path: str | None = _CAVEAT_PATH) -> HudRenderer:
    return HudRenderer(band_count, "v1.2.3", None, font_path)


def test_frame_corner_is_transparent() -> None:
    frame = _renderer().render("Listening")
    assert frame.getpixel((0, 0)) == (0, 0, 0, 0)


def test_frame_box_center_is_box_fill() -> None:
    renderer = _renderer()
    width, height = renderer.size
    frame = renderer.render("", ("", ""), [])
    r, g, b, a = frame.getpixel((width // 2, height // 2))
    assert a > 200
    assert all(
        abs(channel - target) <= 8 for channel, target in zip((r, g, b), (45, 45, 48), strict=True)
    )


def test_spectrum_bars_grow_with_levels() -> None:
    renderer = _renderer()
    loud = np.asarray(renderer.render("", ("", ""), [1.0] * 16))
    quiet = np.asarray(renderer.render("", ("", ""), [0.0] * 16))
    bar = np.array(_BAR_FILL, dtype=np.uint8)
    loud_bars = int(np.all(loud == bar, axis=-1).sum())
    quiet_bars = int(np.all(quiet == bar, axis=-1).sum())
    assert loud_bars > quiet_bars


def test_label_changes_rendered_bytes() -> None:
    renderer = _renderer()
    listening = to_premultiplied_bgra(renderer.render("Listening"))
    idle = to_premultiplied_bgra(renderer.render("Idle"))
    assert listening != idle


def test_missing_caveat_font_falls_back() -> None:
    # A None path and a bogus path must both render without raising.
    for font_path in (None, "/nonexistent/Caveat.ttf"):
        renderer = _renderer(font_path=font_path)
        frame = renderer.render("Ready")
        assert frame.size == renderer.size
        assert frame.mode == "RGBA"


def test_wrap_segments_preserves_stable_provisional_boundary() -> None:
    font = _load_sans_font(12)
    lines = _wrap_segments("hello", " world", 1000.0, font)
    assert lines == [[("hello", False), (" world", True)]]


def test_wrap_segments_truncates_to_two_lines_with_ellipsis() -> None:
    font = _load_sans_font(12)
    long_text = " ".join(f"word{index}" for index in range(40))
    lines = _wrap_segments(long_text, "", 100.0, font)
    assert len(lines) == 2
    assert lines[-1][-1][0].endswith("…")


def test_to_premultiplied_bgra_known_pixel() -> None:
    opaque = to_premultiplied_bgra(Image.new("RGBA", (1, 1), (255, 0, 0, 128)))
    # Straight red at 50% alpha -> premultiplied BGRA little-endian.
    assert list(opaque) == [0, 0, 128, 128]
    transparent = to_premultiplied_bgra(Image.new("RGBA", (1, 1), (255, 255, 255, 0)))
    assert list(transparent) == [0, 0, 0, 0]
