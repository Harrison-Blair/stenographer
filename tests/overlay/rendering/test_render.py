# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import random
import sys
from itertools import pairwise
from types import MappingProxyType

import pytest
from PIL import Image, ImageChops

from stenographer.lib.contracts.constants import SPECTRUM_BANDS
from stenographer.lib.contracts.loading_model import LoadingModel
from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.overlay.rendering.constants import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    EDGE_OFFSET,
    LOADING_ANIMATION_FPS,
    LOADING_BORDER_COLOR,
    LOADING_BORDER_COLORS,
    LOADING_BORDER_INSET,
    LOADING_BORDER_WIDTH,
    LOADING_OPACITY_MAX,
    LOADING_OPACITY_MIN,
    LOADING_PULSE_SECONDS,
    PILL_HEIGHT,
    PILL_WIDTH,
    STATE_DOT_COLORS,
    STATE_LABELS,
)
from stenographer.overlay.rendering.render import (
    _crop_transparent,
    _font,
    layer_margin_bottom,
    loading_border_opacity,
    overlay_position,
    premultiplied_argb32,
    render_overlay,
)
from stenographer.overlay.rendering.render import (
    spectrum_bar_bounds as _spectrum_bar_bounds,
)


def spectrum_bar_bounds(levels, *, scale=1.0):
    return _spectrum_bar_bounds(
        levels, pill_bounds=(8, 5, 8 + PILL_WIDTH, 5 + PILL_HEIGHT), scale=scale
    )


def test_lifecycle_visual_contract_has_no_loading_label_or_dot() -> None:
    assert isinstance(STATE_LABELS, MappingProxyType)
    assert STATE_LABELS == {
        OverlayState.TRANSCRIBING: "Transcribing",
        OverlayState.REFINING: "Refining",
        OverlayState.DELIVERING: "Delivering",
        OverlayState.CANCELLED: "Cancelled",
        OverlayState.ERROR: "Error",
        OverlayState.APPLIED: "Applied",
        OverlayState.SKIPPED: "Skipped",
        OverlayState.FALLBACK: "Fallback",
    }
    assert isinstance(STATE_DOT_COLORS, MappingProxyType)
    assert STATE_DOT_COLORS == {
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
    assert OverlayState.HIDDEN not in STATE_LABELS
    assert OverlayState.RECORDING not in STATE_LABELS


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
        (OverlayState.TRANSCRIBING, (0x3B, 0x82, 0xF6, 0xFF)),
        (OverlayState.DELIVERING, (0x8B, 0x5C, 0xF6, 0xFF)),
        (OverlayState.CANCELLED, (0xA1, 0xA1, 0xAA, 0xFF)),
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
    expected_left = (CANVAS_WIDTH - PILL_WIDTH) // 2
    assert frame.pill_bounds == (expected_left, 5, expected_left + PILL_WIDTH, 48)
    assert frame.pill_bounds[2] - frame.pill_bounds[0] == PILL_WIDTH == 187
    assert frame.pill_bounds[3] - frame.pill_bounds[1] == PILL_HEIGHT == 43
    assert frame.image.getpixel((frame.pill_bounds[0] + 73, frame.pill_bounds[1] + 3)) == (
        0x18,
        0x18,
        0x1B,
        230,
    )
    # The resize to the 5 px dot leaves the center pixel a few levels off the color.
    dot_center = frame.image.getpixel((frame.pill_bounds[2] - 12, frame.pill_bounds[1] + 21))
    assert dot_center == pytest.approx(dot_color, abs=10)
    assert frame.image.tobytes() == same_frame.image.tobytes()


def _ink_runs(frame) -> tuple[list[tuple[int, int]], tuple[int, int]]:
    """Return the runs of ink columns and the row extent of the ink inside the pill.

    A pixel is ink when it visibly differs from the pill fill. The pill edge
    is left out, where the rounded corners blend with the canvas.
    """
    left, top, right, bottom = frame.pill_bounds
    inner = frame.image.crop((left, top + 2, right, bottom - 2))
    fill = Image.new("RGBA", inner.size, (0x18, 0x18, 0x1B, 230))
    difference = ImageChops.difference(inner, fill).convert("RGB").convert("L")
    ink = difference.point(lambda value: 255 if value > 40 else 0)
    ink.paste(0, (0, 0, 4, inner.height))
    ink.paste(0, (inner.width - 4, 0, inner.width, inner.height))
    columns = [any(ink.getpixel((x, y)) for y in range(inner.height)) for x in range(inner.width)]
    runs: list[tuple[int, int]] = []
    for x, has_ink in enumerate(columns):
        if not has_ink:
            continue
        if runs and runs[-1][1] == x:
            runs[-1] = (runs[-1][0], x + 1)
        else:
            runs.append((x, x + 1))
    bounds = ink.getbbox()
    assert bounds is not None
    return runs, (bounds[1] + 2, bounds[3] + 2)


@pytest.mark.parametrize("state", list(STATE_LABELS))
def test_each_label_fits_between_the_logo_and_the_dot_with_no_profile_text(
    state: OverlayState,
) -> None:
    frame = render_overlay(state)
    left, top, right, bottom = frame.pill_bounds
    assert (right - left, bottom - top) == (187, 43)

    runs, (ink_top, ink_bottom) = _ink_runs(frame)
    logo, *label, dot = runs

    # The logo stays left of the text start at 40, and the dot is 5 px centered
    # 12 from the right. A label that touched either one merges with its run.
    assert logo[1] <= 38
    assert dot[0] >= 187 - 12 - 4
    assert dot[1] <= 187 - 12 + 4
    assert label, "the state must draw its label"
    assert logo[1] < label[0][0]
    assert label[-1][1] < dot[0]
    assert ink_top >= 0 and ink_bottom <= 43

    # A profile prefix would add about 30 px to the inked width of the label.
    label_width = label[-1][1] - label[0][0]
    assert label_width <= _font(18).getlength(STATE_LABELS[state]) + 3


@pytest.mark.parametrize("scale", [1.0, 1.25, 1.5, 2.0])
def test_maximum_bars_stay_clear_of_the_logo_and_the_dot(scale: float) -> None:
    levels = (255,) * SPECTRUM_BANDS
    frame = render_overlay(OverlayState.RECORDING, scale=scale, levels=levels)
    left, top, right, bottom = frame.pill_bounds
    bars = _spectrum_bar_bounds(levels, pill_bounds=frame.pill_bounds, scale=scale)

    assert bars[0][0] >= left + round(40 * scale)
    assert bars[-1][2] < right - round(15 * scale)
    assert all(top < bar[1] and bar[3] < bottom for bar in bars)


def test_recording_draws_only_the_logo_the_bars_and_the_dot() -> None:
    frame = render_overlay(OverlayState.RECORDING, levels=(255,) * SPECTRUM_BANDS)
    runs, _rows = _ink_runs(frame)

    assert len(runs) == 1 + 18 + 1
    assert runs[0][1] <= 38
    assert runs[1][0] == 44
    assert runs[18][1] == 44 + 105
    assert runs[-1][0] >= 187 - 12 - 4


def test_recording_bar_geometry_is_exactly_eighteen_rounded_white_baselines() -> None:
    bounds = spectrum_bar_bounds((0,) * SPECTRUM_BANDS)
    full_bounds = spectrum_bar_bounds((255,) * SPECTRUM_BANDS)

    assert SPECTRUM_BANDS == 18
    assert len(bounds) == len(full_bounds) == 18
    assert all(right - left == 3 and bottom - top == 3 for left, top, right, bottom in bounds)
    assert all(bottom - top == 29 for _left, top, _right, bottom in full_bounds)
    assert all(next_bounds[0] - current[2] == 3 for current, next_bounds in pairwise(bounds))

    frame = render_overlay(OverlayState.RECORDING, levels=(255,) * SPECTRUM_BANDS)
    for left, top, right, bottom in full_bounds:
        pixel = frame.image.getpixel(((left + right) // 2, (top + bottom) // 2))
        assert pixel[3] == 255
        assert min(pixel[:3]) >= 250


def test_spectrum_levels_change_only_the_recording_frame() -> None:
    baseline = render_overlay(OverlayState.RECORDING, levels=(0,) * SPECTRUM_BANDS)
    active = render_overlay(OverlayState.RECORDING, levels=(255,) * SPECTRUM_BANDS)
    assert baseline.image.tobytes() != active.image.tobytes()

    with pytest.raises(ValueError, match="recording"):
        render_overlay(OverlayState.TRANSCRIBING, levels=(0,) * SPECTRUM_BANDS)


def test_loading_border_contract_and_sinusoidal_timing_are_exact() -> None:
    assert LOADING_BORDER_COLOR == (0xF5, 0x9E, 0x0B)
    assert LOADING_BORDER_WIDTH == 3
    assert LOADING_BORDER_INSET == 1
    assert LOADING_PULSE_SECONDS == 2.0
    assert LOADING_ANIMATION_FPS == 60
    assert LOADING_OPACITY_MIN == 0.25
    assert LOADING_OPACITY_MAX == 0.85
    assert loading_border_opacity(0.0) == pytest.approx(0.25)
    assert loading_border_opacity(0.5) == pytest.approx(0.55)
    assert loading_border_opacity(1.0) == pytest.approx(0.85)
    assert loading_border_opacity(1.5) == pytest.approx(0.55)
    assert loading_border_opacity(2.0) == pytest.approx(0.25)


def test_loading_border_is_bounded_and_capped_at_sixty_frames_per_second() -> None:
    values = [loading_border_opacity(index / 1000) for index in range(4001)]
    assert min(values) >= LOADING_OPACITY_MIN
    assert max(values) <= LOADING_OPACITY_MAX
    assert loading_border_opacity(0.001) == loading_border_opacity(0.016)
    assert loading_border_opacity(0.017) != loading_border_opacity(0.016)


@pytest.mark.parametrize(
    "elapsed",
    [True, "0", -0.1, float("inf"), float("nan")],
)
def test_loading_border_rejects_invalid_elapsed_time(elapsed: object) -> None:
    with pytest.raises(TypeError if elapsed in (True, "0") else ValueError):
        loading_border_opacity(elapsed)
    with pytest.raises(TypeError if elapsed in (True, "0") else ValueError):
        render_overlay(
            OverlayState.RECORDING, loading_elapsed=elapsed, loading_model=LoadingModel.ASR
        )


@pytest.mark.parametrize("state", list(OverlayState)[1:])
def test_loading_border_is_deterministic_and_does_not_change_pill_geometry(
    state: OverlayState,
) -> None:
    levels = (128,) * SPECTRUM_BANDS if state is OverlayState.RECORDING else None
    baseline = render_overlay(state, levels=levels)
    first = render_overlay(
        state, levels=levels, loading_elapsed=0.75, loading_model=LoadingModel.ASR
    )
    same = render_overlay(
        state, levels=levels, loading_elapsed=0.75, loading_model=LoadingModel.ASR
    )

    assert first.pill_bounds == baseline.pill_bounds
    assert first.image.size == baseline.image.size
    assert first.image.tobytes() == same.image.tobytes()
    assert first.image.tobytes() != baseline.image.tobytes()


def test_hidden_is_not_a_renderable_surface() -> None:
    with pytest.raises(ValueError, match="hidden"):
        render_overlay(OverlayState.HIDDEN)


@pytest.mark.parametrize(
    ("scale", "canvas_size", "pill_bounds"),
    [
        (1.0, (204, 60), (8, 5, 195, 48)),
        (1.25, (255, 75), (10, 6, 244, 60)),
        (1.5, (306, 90), (12, 8, 292, 72)),
        (2.0, (408, 120), (16, 10, 390, 96)),
    ],
)
@pytest.mark.parametrize("state", list(OverlayState)[1:])
def test_rendering_scales_from_logical_geometry(
    state: OverlayState,
    scale: float,
    canvas_size: tuple[int, int],
    pill_bounds: tuple[int, int, int, int],
) -> None:
    frame = render_overlay(state, scale=scale)

    assert frame.scale == scale
    assert frame.image.size == canvas_size
    assert frame.pill_bounds == pill_bounds
    assert frame.stride == canvas_size[0] * 4


@pytest.mark.parametrize("scale", [1.0, 1.25, 1.5, 2.0])
def test_visible_states_and_loading_border_share_canvas_bounds_and_placement(scale: float) -> None:
    output = (100, 200, 1920, 1080)
    frames = [
        render_overlay(
            state,
            scale=scale,
            levels=(128,) * SPECTRUM_BANDS if state is OverlayState.RECORDING else None,
            loading_elapsed=0.75 if bordered else None,
            loading_model=LoadingModel.ASR if bordered else None,
        )
        for state in list(OverlayState)[1:]
        for bordered in (False, True)
    ]

    assert len({frame.image.size for frame in frames}) == 1
    assert len({frame.pill_bounds for frame in frames}) == 1
    assert len({overlay_position(output, frame) for frame in frames}) == 1


@pytest.mark.parametrize("scale", [0, -1, float("inf"), float("nan")])
def test_rendering_rejects_invalid_scale(scale: float) -> None:
    with pytest.raises(ValueError, match="scale"):
        render_overlay(OverlayState.RECORDING, scale=scale)


def test_argb32_conversion_premultiplies_and_obeys_byte_order() -> None:
    image = Image.new("RGBA", (2, 1))
    image.putdata([(255, 128, 1, 128), (7, 8, 9, 0)])

    assert premultiplied_argb32(image, byteorder="little") == bytes([1, 64, 128, 128, 0, 0, 0, 0])
    assert premultiplied_argb32(image, byteorder="big") == bytes([128, 128, 64, 1, 0, 0, 0, 0])


@pytest.mark.parametrize("byteorder", ["little", "big"])
def test_argb32_optimized_conversion_matches_scalar_formula(byteorder: str) -> None:
    randomizer = random.Random(0x51E6)
    pixels = [tuple(randomizer.randrange(256) for _channel in range(4)) for _ in range(2048)]
    image = Image.new("RGBA", (64, 32))
    image.putdata(pixels)
    expected = bytearray()
    for red, green, blue, alpha in pixels:
        premultiplied = tuple((channel * alpha + 127) // 255 for channel in (red, green, blue))
        if byteorder == "little":
            expected.extend((premultiplied[2], premultiplied[1], premultiplied[0], alpha))
        else:
            expected.extend((alpha, premultiplied[0], premultiplied[1], premultiplied[2]))

    assert premultiplied_argb32(image, byteorder=byteorder) == bytes(expected)


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


def test_layer_margin_offsets_visible_pill_not_shadow_canvas() -> None:
    assert layer_margin_bottom(canvas_height=88, pill_bottom=72) == 16


def test_layer_margin_and_position_agree_on_the_pill_edge_offset() -> None:
    frame = render_overlay(OverlayState.RECORDING)
    output = (0, 0, 1920, 1080)

    _x, y = overlay_position(output, frame)
    margin = layer_margin_bottom(canvas_height=frame.height, pill_bottom=frame.pill_bounds[3])

    assert output[3] - (y + frame.pill_bounds[3]) == EDGE_OFFSET
    assert margin + (frame.height - frame.pill_bounds[3]) == EDGE_OFFSET


def test_layer_margin_rejects_a_shadow_canvas_deeper_than_the_offset() -> None:
    with pytest.raises(ValueError, match="edge offset"):
        layer_margin_bottom(canvas_height=88, pill_bottom=40)


# Exact RGBA values sampled from the reference renderer at scale 1.0.  These
# pin the composited output bytes at load-bearing coordinates — loading border,
# spectrum bar interior, state dot center, drop shadow, pill interior, and the
# label region — so cache or compositing-order restructuring cannot silently
# change the rendered frame.
#
# Two of those coordinates land on label glyphs in the states that draw one
# (RECORDING draws no label, so all six are geometry there).  Glyph positions
# come from Pillow's bundled shaping/FreeType build, not from anything here:
# "Transcribing" advances 78.2px through raqm and 80.0px through the BASIC
# layout engine on the same font file, and a ~2px shift changes whether x=53
# and x=89 sit on ink or on a gap.  So the text samples are pinned only on the
# stack they were sampled from, and every geometry sample is pinned everywhere
# — the compositing order, supersample/downscale path, and render cache stay
# covered on every platform.
_GOLDEN_COORDINATES = {
    "border_top": (100, 7),
    "bar_interior": (53, 26),
    "dot_center": (183, 26),
    "shadow_below": (100, 51),
    "pill_interior": (80, 10),
    "label_region": (89, 26),
}

_GOLDEN_RECORDING = {
    "border_top": (200, 131, 13, 249),
    "bar_interior": (255, 255, 255, 255),
    "dot_center": (231, 66, 66, 255),
    "shadow_below": (0, 0, 0, 30),
    "pill_interior": (24, 24, 27, 230),
    "label_region": (255, 255, 255, 255),
}

_GOLDEN_TRANSCRIBING = {
    "border_top": (200, 131, 13, 249),
    "bar_interior": (244, 244, 244, 254),
    "dot_center": (57, 126, 238, 255),
    "shadow_below": (0, 0, 0, 30),
    "pill_interior": (24, 24, 27, 230),
    "label_region": (254, 254, 254, 255),
}


# The two samples that land on label glyphs in a state that draws a label.
_TEXT_SAMPLES = frozenset({"bar_interior", "label_region"})


def _reference_text_stack() -> bool:
    """True on the platform the label goldens were sampled from.

    Linux is the shipped platform and the reference rasterizer; elsewhere the
    Pillow wheel's shaping/FreeType build sets its own glyph advances.
    """
    return sys.platform.startswith("linux")


@pytest.mark.parametrize(
    ("state", "levels", "golden", "text_samples"),
    [
        (OverlayState.RECORDING, (128,) * SPECTRUM_BANDS, _GOLDEN_RECORDING, frozenset()),
        (OverlayState.TRANSCRIBING, None, _GOLDEN_TRANSCRIBING, _TEXT_SAMPLES),
    ],
    ids=["recording", "transcribing"],
)
def test_golden_pixels_pin_composited_output_bytes(
    state: OverlayState,
    levels: tuple[int, ...] | None,
    golden: dict[str, tuple[int, int, int, int]],
    text_samples: frozenset[str],
) -> None:
    frame = render_overlay(
        state, scale=1.0, levels=levels, loading_elapsed=0.75, loading_model=LoadingModel.ASR
    )

    expected = golden
    if text_samples and not _reference_text_stack():
        expected = {name: rgba for name, rgba in golden.items() if name not in text_samples}
    assert expected, "every sample was dropped: the geometry goldens must still be checked"

    sampled = {name: frame.image.getpixel(_GOLDEN_COORDINATES[name]) for name in expected}
    assert sampled == expected


def test_loading_border_colours_follow_the_model() -> None:
    assert LOADING_BORDER_COLORS[LoadingModel.ASR] == LOADING_BORDER_COLOR
    assert LOADING_BORDER_COLORS[LoadingModel.REFINE] == STATE_DOT_COLORS[OverlayState.REFINING][:3]

    asr = render_overlay(
        OverlayState.TRANSCRIBING, loading_elapsed=0.75, loading_model=LoadingModel.ASR
    )
    refine = render_overlay(
        OverlayState.TRANSCRIBING, loading_elapsed=0.75, loading_model=LoadingModel.REFINE
    )
    assert asr.image.tobytes() != refine.image.tobytes()

    with pytest.raises(ValueError, match="loading elapsed time and model"):
        render_overlay(OverlayState.TRANSCRIBING, loading_elapsed=0.75)
    with pytest.raises(ValueError, match="loading elapsed time and model"):
        render_overlay(OverlayState.TRANSCRIBING, loading_model=LoadingModel.ASR)


# Sampled from the reference renderer the same way as ``_GOLDEN_TRANSCRIBING``,
# but with the REFINE model breathing instead of ASR.
_GOLDEN_TRANSCRIBING_REFINE = (21, 152, 137, 249)


def test_the_refine_border_pixel_is_the_refining_colour_over_the_pill() -> None:
    frame = render_overlay(
        OverlayState.TRANSCRIBING,
        scale=1.0,
        loading_elapsed=0.75,
        loading_model=LoadingModel.REFINE,
    )

    sampled = frame.image.getpixel(_GOLDEN_COORDINATES["border_top"])

    assert sampled == _GOLDEN_TRANSCRIBING_REFINE
    assert sampled != _GOLDEN_TRANSCRIBING["border_top"]
    assert sampled[3] == _GOLDEN_TRANSCRIBING["border_top"][3]
    red, green, blue, _alpha = sampled
    assert green > red
    assert blue > red


def test_an_entirely_transparent_image_has_no_visible_bounds_to_crop() -> None:
    """Seen to matter for the packaged icon: an empty crop box would make PIL
    raise deep inside the render rather than at the asset that is wrong.
    """
    with pytest.raises(ValueError, match="no visible pixels"):
        _crop_transparent(Image.new("RGBA", (8, 8), (0, 0, 0, 0)))


@pytest.mark.parametrize(
    "levels",
    [(0,) * (SPECTRUM_BANDS - 1), (0,) * (SPECTRUM_BANDS + 1), "0" * SPECTRUM_BANDS, 0],
)
def test_spectrum_geometry_requires_exactly_eighteen_levels(levels: object) -> None:
    with pytest.raises(ValueError, match=f"{SPECTRUM_BANDS} levels"):
        spectrum_bar_bounds(levels)


@pytest.mark.parametrize(
    "level", [256, -1, True, 1.0, "255"], ids=["over", "under", "bool", "float", "text"]
)
def test_spectrum_geometry_requires_whole_bytes_for_every_bar(level: object) -> None:
    levels = (0,) * (SPECTRUM_BANDS - 1) + (level,)

    with pytest.raises(ValueError, match="integers from 0 to 255"):
        spectrum_bar_bounds(levels)


@pytest.mark.parametrize("scale", [0, -1.0, float("inf"), float("nan")])
def test_spectrum_geometry_rejects_a_scale_that_cannot_size_a_bar(scale: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        spectrum_bar_bounds(None, scale=scale)


def test_spectrum_geometry_treats_no_levels_as_eighteen_silent_bars() -> None:
    assert spectrum_bar_bounds(None) == spectrum_bar_bounds((0,) * SPECTRUM_BANDS)


@pytest.mark.parametrize("state", ["recording", 0, None])
def test_rendering_requires_a_real_lifecycle_state(state: object) -> None:
    with pytest.raises(TypeError, match="OverlayState"):
        render_overlay(state)


@pytest.mark.parametrize("scale", [True, "1.0", None])
def test_rendering_requires_a_numeric_scale_rather_than_a_truthy_one(scale: object) -> None:
    """``True`` is a number in Python and would render a scale-1.0 frame that
    the caller believed was something else.
    """
    with pytest.raises(TypeError, match="scale must be a number"):
        render_overlay(OverlayState.RECORDING, scale=scale)


@pytest.mark.parametrize("byteorder", ["middle", "LITTLE", ""])
def test_argb32_conversion_refuses_an_unknown_byte_order(byteorder: str) -> None:
    with pytest.raises(ValueError, match="little or big"):
        premultiplied_argb32(Image.new("RGBA", (1, 1)), byteorder=byteorder)


@pytest.mark.parametrize(
    "output_rect",
    [(0, 0, 1920), (0, 0, 1920, 1080, 0), (0, 0, 1920.0, 1080), (0, 0, True, 1080)],
)
def test_position_requires_four_whole_pixel_output_bounds(output_rect: tuple) -> None:
    frame = render_overlay(OverlayState.ERROR)

    with pytest.raises(TypeError, match="four integers"):
        overlay_position(output_rect, frame)
