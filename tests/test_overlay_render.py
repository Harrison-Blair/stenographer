# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import random
from itertools import pairwise
from types import MappingProxyType

import pytest
from PIL import Image

from stenographer.overlay_render import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    EDGE_OFFSET,
    LOADING_ANIMATION_FPS,
    LOADING_BORDER_COLOR,
    LOADING_BORDER_INSET,
    LOADING_BORDER_WIDTH,
    LOADING_FRAME_INTERVAL,
    LOADING_OPACITY_MAX,
    LOADING_OPACITY_MIN,
    LOADING_PULSE_SECONDS,
    PILL_HEIGHT,
    PILL_WIDTH,
    STATE_DOT_COLORS,
    STATE_LABELS,
    LoadingPulse,
    _crop_transparent,
    loading_border_opacity,
    overlay_position,
    premultiplied_argb32,
    render_overlay,
    spectrum_bar_bounds,
)
from stenographer.status import SPECTRUM_BANDS, OverlayState


def test_lifecycle_visual_contract_has_no_loading_label_or_dot() -> None:
    assert isinstance(STATE_LABELS, MappingProxyType)
    assert STATE_LABELS == {
        OverlayState.TRANSCRIBING: "Transcribing",
        OverlayState.DELIVERING: "Delivering",
        OverlayState.ERROR: "Error",
    }
    assert isinstance(STATE_DOT_COLORS, MappingProxyType)
    assert STATE_DOT_COLORS == {
        OverlayState.RECORDING: (0xEF, 0x44, 0x44, 0xFF),
        OverlayState.TRANSCRIBING: (0x3B, 0x82, 0xF6, 0xFF),
        OverlayState.DELIVERING: (0x8B, 0x5C, 0xF6, 0xFF),
        OverlayState.ERROR: (0xEF, 0x44, 0x44, 0xFF),
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
    assert frame.pill_bounds == (expected_left, 8, expected_left + PILL_WIDTH, 72)
    assert frame.pill_bounds[2] - frame.pill_bounds[0] == PILL_WIDTH == 280
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


def test_recording_bar_geometry_is_exactly_eighteen_rounded_white_baselines() -> None:
    bounds = spectrum_bar_bounds((0,) * SPECTRUM_BANDS)
    full_bounds = spectrum_bar_bounds((255,) * SPECTRUM_BANDS)

    assert SPECTRUM_BANDS == 18
    assert len(bounds) == len(full_bounds) == 18
    assert all(right - left == 5 and bottom - top == 4 for left, top, right, bottom in bounds)
    assert all(bottom - top == 44 for _left, top, _right, bottom in full_bounds)
    assert all(next_bounds[0] - current[2] == 4 for current, next_bounds in pairwise(bounds))

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
    assert LOADING_BORDER_WIDTH == 4
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
        render_overlay(OverlayState.RECORDING, loading_elapsed=elapsed)


def test_loading_pulse_dedupes_activity_edges_and_tracks_start_time() -> None:
    pulse = LoadingPulse()
    assert pulse.set_active(False, 10.0) is False
    assert pulse.set_active(True, 10.0) is True
    assert pulse.started_at == 10.0
    assert pulse.set_active(True, 11.0) is False
    assert pulse.started_at == 10.0
    assert pulse.set_active(False, 12.0) is True
    assert pulse.started_at is None
    assert pulse.next_frame_at is None
    assert pulse.set_active(False, 13.0) is False


def test_loading_pulse_elapsed_is_clamped_and_none_while_inactive() -> None:
    pulse = LoadingPulse()
    assert pulse.elapsed(10.0) is None
    pulse.set_active(True, 10.0)
    assert pulse.elapsed(12.5) == 2.5
    assert pulse.elapsed(9.0) == 0.0
    pulse.set_active(False, 13.0)
    assert pulse.elapsed(14.0) is None


def test_loading_pulse_timeout_requires_active_visible_and_armed_deadline() -> None:
    pulse = LoadingPulse()
    assert pulse.timeout(10.0, True) is None
    pulse.set_active(True, 10.0)
    assert pulse.timeout(10.0, True) is None
    pulse.arm(10.0)
    assert pulse.timeout(10.0, False) is None
    assert pulse.timeout(10.0, True) == pytest.approx(LOADING_FRAME_INTERVAL)
    assert pulse.timeout(10.0 + 2 * LOADING_FRAME_INTERVAL, True) == 0.0
    pulse.set_active(False, 11.0)
    assert pulse.timeout(11.0, True) is None


def test_loading_pulse_frame_due_fires_at_the_deadline_and_advances_cadence() -> None:
    pulse = LoadingPulse()
    pulse.set_active(True, 100.0)
    pulse.arm(100.0)
    assert pulse.frame_due(100.0, True) is False
    due_at = 100.0 + LOADING_FRAME_INTERVAL
    assert pulse.frame_due(due_at, False) is False
    assert pulse.frame_due(due_at, True) is True
    pulse.advance(due_at)
    assert pulse.next_frame_at == pytest.approx(due_at + LOADING_FRAME_INTERVAL)
    assert pulse.frame_due(due_at, True) is False
    assert pulse.frame_due(due_at + LOADING_FRAME_INTERVAL, True) is True


def test_loading_pulse_disarm_clears_only_the_frame_deadline() -> None:
    pulse = LoadingPulse()
    pulse.set_active(True, 50.0)
    pulse.arm(50.0)
    pulse.disarm_frames()
    assert pulse.next_frame_at is None
    assert pulse.active is True
    assert pulse.started_at == 50.0
    assert pulse.timeout(51.0, True) is None
    assert pulse.frame_due(51.0, True) is False
    pulse.arm(51.0)
    assert pulse.next_frame_at == pytest.approx(51.0 + LOADING_FRAME_INTERVAL)
    assert pulse.elapsed(51.0) == 1.0


@pytest.mark.parametrize("state", list(OverlayState)[1:])
def test_loading_border_is_deterministic_and_does_not_change_pill_geometry(
    state: OverlayState,
) -> None:
    levels = (128,) * SPECTRUM_BANDS if state is OverlayState.RECORDING else None
    baseline = render_overlay(state, levels=levels)
    first = render_overlay(state, levels=levels, loading_elapsed=0.75)
    same = render_overlay(state, levels=levels, loading_elapsed=0.75)

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
        (1.0, (304, 88), (12, 8, 292, 72)),
        (1.25, (380, 110), (15, 10, 365, 90)),
        (1.5, (456, 132), (18, 12, 438, 108)),
        (2.0, (608, 176), (24, 16, 584, 144)),
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


# Exact RGBA values sampled from the reference renderer at scale 1.0.  These
# pin the composited output bytes at load-bearing coordinates — loading border,
# spectrum bar interior, state dot center, drop shadow, pill interior, and the
# label region — so cache or compositing-order restructuring cannot silently
# change the rendered frame.
_GOLDEN_COORDINATES = {
    "border_top": (150, 11),
    "bar_interior": (86, 40),
    "dot_center": (274, 40),
    "shadow_below": (150, 76),
    "pill_interior": (122, 20),
    "label_region": (140, 40),
}

_GOLDEN_RECORDING = {
    "border_top": (197, 129, 14, 249),
    "bar_interior": (253, 253, 253, 255),
    "dot_center": (239, 68, 68, 255),
    "shadow_below": (0, 0, 0, 33),
    "pill_interior": (24, 24, 27, 230),
    "label_region": (253, 253, 253, 255),
}

_GOLDEN_TRANSCRIBING = {
    "border_top": (197, 129, 14, 249),
    "bar_interior": (99, 99, 101, 238),
    "dot_center": (59, 130, 246, 255),
    "shadow_below": (0, 0, 0, 33),
    "pill_interior": (24, 24, 27, 230),
    "label_region": (253, 253, 253, 255),
}


@pytest.mark.parametrize(
    ("state", "levels", "golden"),
    [
        (OverlayState.RECORDING, (128,) * SPECTRUM_BANDS, _GOLDEN_RECORDING),
        (OverlayState.TRANSCRIBING, None, _GOLDEN_TRANSCRIBING),
    ],
    ids=["recording", "transcribing"],
)
def test_golden_pixels_pin_composited_output_bytes(
    state: OverlayState,
    levels: tuple[int, ...] | None,
    golden: dict[str, tuple[int, int, int, int]],
) -> None:
    frame = render_overlay(state, scale=1.0, levels=levels, loading_elapsed=0.75)

    sampled = {
        name: frame.image.getpixel(coordinates) for name, coordinates in _GOLDEN_COORDINATES.items()
    }
    assert sampled == golden
