# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from types import MappingProxyType

import pytest
from PIL import Image

from stenographer.overlay_render import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    EDGE_OFFSET,
    PILL_HEIGHT,
    PILL_WIDTH,
    STATE_DOT_COLORS,
    STATE_LABELS,
    _crop_transparent,
    overlay_position,
    premultiplied_argb32,
    render_overlay,
)
from stenographer.status import OverlayState


def test_lifecycle_visual_contract_is_fixed_and_metadata_only() -> None:
    assert isinstance(STATE_LABELS, MappingProxyType)
    assert STATE_LABELS == {
        OverlayState.RECORDING: "Recording",
        OverlayState.MODEL_LOADING: "Loading model",
        OverlayState.TRANSCRIBING: "Transcribing",
        OverlayState.DELIVERING: "Delivering",
        OverlayState.ERROR: "Error",
    }
    assert isinstance(STATE_DOT_COLORS, MappingProxyType)
    assert STATE_DOT_COLORS == {
        OverlayState.RECORDING: (0xEF, 0x44, 0x44, 0xFF),
        OverlayState.MODEL_LOADING: (0xF5, 0x9E, 0x0B, 0xFF),
        OverlayState.TRANSCRIBING: (0x3B, 0x82, 0xF6, 0xFF),
        OverlayState.DELIVERING: (0x8B, 0x5C, 0xF6, 0xFF),
        OverlayState.ERROR: (0xEF, 0x44, 0x44, 0xFF),
    }
    assert OverlayState.HIDDEN not in STATE_LABELS


def test_transparent_icon_padding_is_cropped_without_mutating_source() -> None:
    source = Image.new("RGBA", (9, 7), (0, 0, 0, 0))
    source.putpixel((3, 2), (255, 255, 255, 255))
    source.putpixel((5, 4), (255, 255, 255, 128))

    cropped = _crop_transparent(source)

    assert cropped.size == (3, 3)
    assert cropped.getchannel("A").getbbox() == (0, 0, 3, 3)
    assert source.size == (9, 7)
    assert source.getpixel((0, 0)) == (0, 0, 0, 0)


@pytest.mark.parametrize(
    ("state", "dot_color"),
    [
        (OverlayState.RECORDING, (0xEF, 0x44, 0x44, 0xFF)),
        (OverlayState.MODEL_LOADING, (0xF5, 0x9E, 0x0B, 0xFF)),
        (OverlayState.TRANSCRIBING, (0x3B, 0x82, 0xF6, 0xFF)),
        (OverlayState.DELIVERING, (0x8B, 0x5C, 0xF6, 0xFF)),
        (OverlayState.ERROR, (0xEF, 0x44, 0x44, 0xFF)),
    ],
)
def test_rendered_pill_geometry_palette_and_determinism(
    state: OverlayState, dot_color: tuple[int, int, int, int]
) -> None:
    frame = render_overlay(state)
    same_frame = render_overlay(state)

    assert frame.image.mode == "RGBA"
    assert frame.image.size == (CANVAS_WIDTH, CANVAS_HEIGHT)
    assert frame.pill_bounds == (12, 8, 12 + PILL_WIDTH, 8 + PILL_HEIGHT)
    assert frame.pill_bounds[2] - frame.pill_bounds[0] == PILL_WIDTH == 220
    assert frame.pill_bounds[3] - frame.pill_bounds[1] == PILL_HEIGHT == 64
    assert frame.image.getpixel((frame.pill_bounds[0] + 110, frame.pill_bounds[1] + 12)) == (
        0x18,
        0x18,
        0x1B,
        230,
    )
    assert frame.image.getpixel((frame.pill_bounds[2] - 18, frame.pill_bounds[1] + 32)) == (
        dot_color
    )
    assert frame.image.tobytes() == same_frame.image.tobytes()


def test_hidden_is_not_a_renderable_surface() -> None:
    with pytest.raises(ValueError, match="hidden"):
        render_overlay(OverlayState.HIDDEN)


@pytest.mark.parametrize(
    ("scale", "canvas_size", "pill_bounds"),
    [
        (1.0, (244, 88), (12, 8, 232, 72)),
        (1.25, (305, 110), (15, 10, 290, 90)),
        (1.5, (366, 132), (18, 12, 348, 108)),
        (2.0, (488, 176), (24, 16, 464, 144)),
    ],
)
def test_rendering_scales_from_logical_geometry(
    scale: float,
    canvas_size: tuple[int, int],
    pill_bounds: tuple[int, int, int, int],
) -> None:
    frame = render_overlay(OverlayState.TRANSCRIBING, scale=scale)

    assert frame.scale == scale
    assert frame.image.size == canvas_size
    assert frame.pill_bounds == pill_bounds
    assert frame.stride == canvas_size[0] * 4


@pytest.mark.parametrize("scale", [0, -1, float("inf"), float("nan")])
def test_rendering_rejects_invalid_scale(scale: float) -> None:
    with pytest.raises(ValueError, match="scale"):
        render_overlay(OverlayState.RECORDING, scale=scale)


def test_argb32_conversion_premultiplies_and_obeys_byte_order() -> None:
    image = Image.new("RGBA", (2, 1))
    image.putdata([(255, 128, 1, 128), (7, 8, 9, 0)])

    assert premultiplied_argb32(image, byteorder="little") == bytes([1, 64, 128, 128, 0, 0, 0, 0])
    assert premultiplied_argb32(image, byteorder="big") == bytes([128, 128, 64, 1, 0, 0, 0, 0])


def test_position_uses_visible_pill_for_exact_bottom_offset() -> None:
    frame = render_overlay(OverlayState.DELIVERING, scale=1.5)
    output = (100, 200, 1920, 1080)

    x, y = overlay_position(output, frame)

    assert x == output[0] + (output[2] - frame.width) // 2
    assert y + frame.pill_bounds[3] == output[1] + output[3] - round(EDGE_OFFSET * frame.scale)
    assert EDGE_OFFSET == 32


def test_position_rejects_output_too_small_for_visible_pill() -> None:
    frame = render_overlay(OverlayState.ERROR)

    with pytest.raises(ValueError, match="output"):
        overlay_position((0, 0, PILL_WIDTH - 1, 480), frame)
