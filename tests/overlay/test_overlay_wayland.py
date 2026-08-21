# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure tests for native overlay scale and registry policy."""

from __future__ import annotations

from stenographer.overlay.wayland import (
    REQUIRED_GLOBALS,
    RegistryInventory,
    ScalePlan,
    callback_is_current,
    choose_scale_plan,
    layer_margin_bottom,
)


def test_registry_requires_compositor_shm_and_layer_shell():
    inventory = RegistryInventory()
    for name, interface in enumerate(sorted(REQUIRED_GLOBALS), start=1):
        inventory.add(name, interface, 99)

    assert inventory.missing_required() == ()
    assert inventory.version("wl_compositor") > 0


def test_registry_reports_stable_missing_order_and_removes_globals():
    inventory = RegistryInventory()
    inventory.add(4, "wl_compositor", 6)
    inventory.add(9, "wl_shm", 1)

    assert inventory.missing_required() == ("zwlr_layer_shell_v1",)
    inventory.remove(9)
    assert inventory.missing_required() == ("wl_shm", "zwlr_layer_shell_v1")


def test_registry_rejects_required_global_versions_too_old_for_used_requests():
    inventory = RegistryInventory()
    inventory.add(1, "wl_compositor", 2)
    inventory.add(2, "wl_shm", 1)
    inventory.add(3, "zwlr_layer_shell_v1", 1)

    assert inventory.missing_required() == ("wl_compositor",)


def test_integer_scale_plan_uses_surface_buffer_scale():
    assert choose_scale_plan(integer_scale=2) == ScalePlan(
        render_scale=2.0,
        buffer_scale=2,
        viewport_destination=None,
    )


def test_fractional_scale_plan_uses_viewporter_in_logical_pixels():
    assert choose_scale_plan(integer_scale=2, preferred_scale_120=180) == ScalePlan(
        render_scale=1.5,
        buffer_scale=1,
        viewport_destination=(304, 88),
    )


def test_invalid_scale_hints_fall_back_safely():
    assert choose_scale_plan(integer_scale=0).render_scale == 1.0
    assert choose_scale_plan(integer_scale=3, preferred_scale_120=0).render_scale == 3.0


def test_layer_margin_offsets_visible_pill_not_shadow_canvas():
    assert layer_margin_bottom(canvas_height=88, pill_bottom=72, edge_offset=32) == 16


def test_callback_epoch_policy_uses_identity_and_rejects_destroyed_epoch():
    current = object()
    stale = object()

    assert callback_is_current(current, current) is True
    assert callback_is_current(stale, current) is False
    assert callback_is_current(current, None) is False


def test_callback_epoch_policy_does_not_accept_merely_equal_tokens():
    class EqualToken:
        def __eq__(self, other: object) -> bool:
            return isinstance(other, EqualToken)

    current = EqualToken()
    stale = EqualToken()
    assert current == stale
    assert callback_is_current(stale, current) is False
