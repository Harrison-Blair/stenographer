# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure monitor, DPI, placement, and upload policy for the X11 fallback."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from Xlib import X

from stenographer.overlay_render import EDGE_OFFSET, render_overlay
from stenographer.overlay_x11 import (
    Monitor,
    PictFormat,
    Placement,
    StackingReassertPlan,
    choose_dpi_scale,
    consume_stacking_reassert,
    freeze_placement,
    parse_xft_dpi,
    plan_upload_chunks,
    select_argb_visual,
    select_monitor,
    stacking_reassert_timeout,
    start_stacking_reassert,
    x11_position,
)
from stenographer.status import OverlayState


def _monitor(
    output: int,
    rect: tuple[int, int, int, int],
    *,
    primary: bool = False,
    connected: bool = True,
) -> Monitor:
    return Monitor(output, *rect, primary=primary, connected=connected)


def test_pointer_monitor_wins_over_primary_and_disconnected_outputs() -> None:
    monitors = (
        _monitor(1, (0, 0, 1920, 1080), primary=True),
        _monitor(2, (1920, 0, 2560, 1440)),
        _monitor(3, (1920, 0, 2560, 1440), connected=False),
    )

    selected = select_monitor(monitors, pointer=(2500, 500), root_rect=(0, 0, 4480, 1440))

    assert selected.output == 2
    assert selected.rect == (1920, 0, 2560, 1440)


def test_primary_then_root_are_stable_fallbacks() -> None:
    primary = _monitor(7, (100, 50, 1600, 900), primary=True)
    assert select_monitor((primary,), pointer=(-10, -10), root_rect=(0, 0, 1920, 1080)) == primary

    root = select_monitor((), pointer=(3, 4), root_rect=(-100, 0, 2000, 1200))
    assert root.output is None
    assert root.rect == (-100, 0, 2000, 1200)
    assert root.connected is True


def test_monitor_selection_rejects_invalid_root_geometry() -> None:
    with pytest.raises(ValueError, match="root"):
        select_monitor((), pointer=(0, 0), root_rect=(0, 0, 0, 1080))


def test_argb_visual_requires_an_authoritative_render_alpha_mask() -> None:
    xrgb = SimpleNamespace(
        visual_id=10,
        visual_class=X.TrueColor,
        red_mask=0xFF0000,
        green_mask=0x00FF00,
        blue_mask=0x0000FF,
    )
    argb = SimpleNamespace(
        visual_id=11,
        visual_class=X.TrueColor,
        red_mask=0xFF0000,
        green_mask=0x00FF00,
        blue_mask=0x0000FF,
    )
    formats = {
        20: PictFormat(20, 1, 32, 0, 0),
        21: PictFormat(21, 1, 32, 24, 0xFF),
    }

    selected = select_argb_visual((xrgb, argb), {10: 20, 11: 21}, formats)

    assert selected == (argb, formats[21])
    assert select_argb_visual((xrgb,), {10: 20}, formats) is None


def test_placement_scale_and_output_are_frozen_until_hidden() -> None:
    first_monitor = _monitor(1, (0, 0, 1920, 1080), primary=True)
    other_monitor = _monitor(2, (1920, 0, 2560, 1440))
    first = freeze_placement(None, first_monitor, 1.0)

    retained = freeze_placement(first, other_monitor, 2.0)

    assert first == Placement(first_monitor, 1.0)
    assert retained is first


def test_post_map_stacking_reassert_is_bounded_timed_and_epoch_guarded() -> None:
    plan = start_stacking_reassert(epoch=7, now=100.0)

    assert plan == StackingReassertPlan(7, (100.1, 100.75))
    assert stacking_reassert_timeout(plan, current_epoch=7, now=100.0) == pytest.approx(0.1)
    due, same = consume_stacking_reassert(plan, current_epoch=7, now=100.05)
    assert due is False
    assert same is plan

    due, remaining = consume_stacking_reassert(plan, current_epoch=7, now=100.11)
    assert due is True
    assert remaining == StackingReassertPlan(7, (100.75,))

    due, finished = consume_stacking_reassert(remaining, current_epoch=7, now=100.8)
    assert due is True
    assert finished is None

    due, stale = consume_stacking_reassert(plan, current_epoch=8, now=100.11)
    assert due is False
    assert stale is None


def test_xft_dpi_parser_is_exact_and_ignores_malformed_values() -> None:
    resources = "Xcursor.size:\t24\nXft.dpi:\t144\nXft.hinting:\t1\n"
    assert parse_xft_dpi(resources) == 144.0
    assert parse_xft_dpi("Xft.dpi:\tfast\n") is None
    assert parse_xft_dpi("NotXft.dpi:\t144\n") is None
    assert parse_xft_dpi(None) is None


def test_dpi_scale_prefers_sane_xft_hint_then_physical_dpi() -> None:
    assert choose_dpi_scale(xft_dpi=144, pixel_width=3840, millimeter_width=600) == 1.5
    physical = choose_dpi_scale(xft_dpi=900, pixel_width=3840, millimeter_width=600)
    assert physical == pytest.approx((3840 * 25.4 / 600) / 96)
    assert choose_dpi_scale(xft_dpi=None, pixel_width=1920, millimeter_width=0) == 1.0


def test_upload_plan_chunks_whole_rows_below_the_x_request_limit() -> None:
    chunks = plan_upload_chunks(width=244, height=88, max_request_bytes=4096)

    assert chunks[0] == (0, 4)
    assert chunks[-1][0] + chunks[-1][1] == 88
    assert sum(height for _y, height in chunks) == 88
    assert all(height * 244 * 4 + 24 <= 4096 for _y, height in chunks)


def test_upload_plan_rejects_a_request_too_small_for_one_row() -> None:
    with pytest.raises(ValueError, match="row"):
        plan_upload_chunks(width=244, height=88, max_request_bytes=999)


def test_x_position_offsets_visible_pill_not_shadow_canvas() -> None:
    frame = render_overlay(OverlayState.RECORDING, scale=1.25)
    monitor = _monitor(9, (120, 80, 2560, 1440))

    x, y = x11_position(monitor, frame)

    assert x == monitor.x + (monitor.width - frame.width) // 2
    assert y + frame.pill_bounds[3] == (
        monitor.y + monitor.height - round(EDGE_OFFSET * frame.scale)
    )
