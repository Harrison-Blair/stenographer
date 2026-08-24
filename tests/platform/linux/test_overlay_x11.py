# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure monitor, DPI, placement, upload, and RENDER-reply policy for X11."""

from __future__ import annotations

import struct
from types import SimpleNamespace

import pytest

pytest.importorskip("Xlib")

from Xlib import X

from stenographer.overlay.render import EDGE_OFFSET, overlay_position, render_overlay
from stenographer.platform.linux.overlay_backends.x11 import (
    Monitor,
    PictFormat,
    Placement,
    StackingReassertPlan,
    choose_dpi_scale,
    consume_stacking_reassert,
    freeze_placement,
    parse_pict_format_screens,
    parse_xft_dpi,
    placement_output_vanished,
    plan_upload_chunks,
    select_argb_visual,
    select_monitor,
    stacking_reassert_timeout,
    start_stacking_reassert,
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

    x, y = overlay_position(monitor.rect, frame)

    assert x == monitor.x + (monitor.width - frame.width) // 2
    assert y + frame.pill_bounds[3] == (
        monitor.y + monitor.height - round(EDGE_OFFSET * frame.scale)
    )


def _pict_screen(depths: list[tuple[int, list[tuple[int, int]]]]) -> bytes:
    """Build one RENDER screen block: depths -> (visual, format) pairs."""
    data = bytearray(struct.pack("=LL", len(depths), 0))
    for depth, visuals in depths:
        data += struct.pack("=BBHL", depth, 0, len(visuals), 0)
        for visual_id, format_id in visuals:
            data += struct.pack("=LL", visual_id, format_id)
    return bytes(data)


def test_render_reply_maps_every_visual_across_screens_and_depths() -> None:
    screens = _pict_screen([(24, [(0x21, 4)]), (32, [(0x22, 7), (0x23, 8)])]) + _pict_screen(
        [(32, [(0x31, 9)])]
    )

    assert parse_pict_format_screens(screens, 2) == {0x21: 4, 0x22: 7, 0x23: 8, 0x31: 9}


def test_a_truncated_render_reply_is_rejected_not_partially_believed() -> None:
    screens = _pict_screen([(32, [(0x22, 7), (0x23, 8)])])

    with pytest.raises(ValueError, match="truncated"):
        parse_pict_format_screens(screens[:-4], 1)
    with pytest.raises(ValueError, match="truncated"):
        parse_pict_format_screens(screens, 2)
    with pytest.raises(ValueError, match="truncated"):
        parse_pict_format_screens(b"", 1)


def test_an_empty_render_reply_maps_nothing_without_raising() -> None:
    assert parse_pict_format_screens(b"", 0) == {}


def test_only_a_vanished_selected_output_permits_relocation() -> None:
    placement = Placement(_monitor(9, (0, 0, 2560, 1440)), 1.0)

    assert placement_output_vanished(placement, {9, 11}) is False
    assert placement_output_vanished(placement, {11}) is True
    assert placement_output_vanished(placement, set()) is True


def test_the_root_fallback_placement_never_vanishes() -> None:
    root = Placement(Monitor(None, 0, 0, 1920, 1080), 1.0)

    assert placement_output_vanished(root, set()) is False
    assert placement_output_vanished(None, set()) is False
