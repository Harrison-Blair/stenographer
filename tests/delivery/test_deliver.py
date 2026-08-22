# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for deliver.py: chord_events() ordering and pick_backend().

The copy round trips (wl-copy and xclip) and the uinput device are covered by
the integration smoke suite in test_deliver_smoke.py — nothing here mocks
subprocess/UInput (§6).
"""

from __future__ import annotations

from stenographer.delivery.deliver import (
    _INSERT,
    _SHIFT,
    ClipboardBackend,
    chord_events,
    copy_both_selections,
    copy_both_selections_x11,
    copy_for_backend,
    pick_backend,
)


def test_chord_events_exact_sequence():
    # The load-bearing invariant: Shift press wraps the Insert press+release.
    assert chord_events() == [(_SHIFT, 1), (_INSERT, 1), (_INSERT, 0), (_SHIFT, 0)]


def test_every_press_has_a_matching_release():
    # A pressed code (value 1) that is never released (value 0) leaves a key
    # latched in the compositor's seat state.
    events = chord_events()
    pressed = [code for code, value in events if value == 1]
    released = [code for code, value in events if value == 0]
    assert sorted(pressed) == sorted(released)


def test_insert_released_before_shift():
    events = chord_events()
    insert_release = events.index((_INSERT, 0))
    shift_release = events.index((_SHIFT, 0))
    assert insert_release < shift_release


def test_shift_is_the_outer_wrapper():
    events = chord_events()
    # Shift down is first and Shift up is last: it wraps everything between.
    assert events[0] == (_SHIFT, 1)
    assert events[-1] == (_SHIFT, 0)


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
