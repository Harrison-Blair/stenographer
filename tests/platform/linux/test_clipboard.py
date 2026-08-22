# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for the clipboard writers: pick_backend() and copy_for_backend().

The copy round trips (wl-copy and xclip) are covered by the integration smoke
suite in tests/delivery/test_deliver_smoke.py — nothing here mocks subprocess (§6).
"""

from __future__ import annotations

from stenographer.platform.linux.clipboard import (
    ClipboardBackend,
    copy_both_selections,
    copy_both_selections_x11,
    copy_for_backend,
    pick_backend,
)


def test_pick_backend_prefers_wl_copy_with_ext_data_control():
    globals_seen = {"wl_compositor", "ext_data_control_manager_v1"}
    assert pick_backend(globals_seen, have_display=True) is ClipboardBackend.WL_COPY


def test_pick_backend_prefers_wl_copy_with_zwlr_data_control():
    globals_seen = {"wl_compositor", "zwlr_data_control_manager_v1"}
    assert pick_backend(globals_seen, have_display=False) is ClipboardBackend.WL_COPY


def test_pick_backend_x11_when_no_data_control_and_display_present():
    # GNOME <= 46: no data-control global; XWayland available.
    globals_seen = {"wl_compositor", "wl_shm", "xdg_wm_base"}
    assert pick_backend(globals_seen, have_display=True) is ClipboardBackend.X11


def test_pick_backend_keeps_wl_copy_without_any_alternative():
    # No data-control AND no X display: stay on wl-copy (status quo; its
    # failure is already the safe no-chord path).
    assert pick_backend(set(), have_display=False) is ClipboardBackend.WL_COPY


def test_copy_for_backend_maps_each_backend_to_its_copier():
    assert copy_for_backend(ClipboardBackend.WL_COPY) is copy_both_selections
    assert copy_for_backend(ClipboardBackend.X11) is copy_both_selections_x11
