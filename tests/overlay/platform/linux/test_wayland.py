# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure tests for native overlay scale, registry, and flush policy."""

from __future__ import annotations

import errno
import mmap

import pytest

pytest.importorskip("pywayland")

from stenographer.overlay.platform.linux.backends.global_removal import GlobalRemoval
from stenographer.overlay.platform.linux.backends.registry_inventory import RegistryInventory
from stenographer.overlay.platform.linux.backends.scale_plan import ScalePlan
from stenographer.overlay.platform.linux.backends.shm_buffer import _ShmBuffer
from stenographer.overlay.platform.linux.backends.wayland import (
    callback_is_current,
    choose_scale_plan,
    classify_global_removal,
    flush_wants_write,
)
from stenographer.overlay.platform.linux.backends.wayland_constants import REQUIRED_GLOBALS


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


def test_losing_a_required_global_is_unrecoverable_and_hotplug_is_not():
    assert classify_global_removal("wl_compositor") is GlobalRemoval.LOST
    assert classify_global_removal("zwlr_layer_shell_v1") is GlobalRemoval.LOST
    assert classify_global_removal("wl_output") is GlobalRemoval.OUTPUT
    assert classify_global_removal("wp_viewporter") is GlobalRemoval.IGNORE


def test_an_unknown_global_name_is_ignored_rather_than_treated_as_a_loss():
    assert classify_global_removal(None) is GlobalRemoval.IGNORE


def test_a_full_socket_asks_for_write_interest_instead_of_failing():
    assert flush_wants_write(0, errno.EPIPE) is False
    assert flush_wants_write(12, 0) is False
    assert flush_wants_write(-1, errno.EAGAIN) is True
    assert flush_wants_write(-1, errno.EWOULDBLOCK) is True


def test_any_other_short_flush_is_a_lost_connection():
    with pytest.raises(RuntimeError, match="flush"):
        flush_wants_write(-1, errno.EPIPE)


def test_the_inventory_lists_every_global_it_still_holds():
    inventory = RegistryInventory()
    inventory.add(4, "wl_compositor", 6)
    inventory.add(9, "wl_shm", 1)
    inventory.remove(4)

    assert tuple(item.interface for item in inventory.values()) == ("wl_shm",)


def test_a_buffer_release_never_raises_out_of_the_frame_loop():
    """Both halves fail independently on a dying compositor: the proxy is gone
    with the connection, and the mapping is still held by a buffer the server
    has not released. Either raising would abort the frame that was cleaning up.
    """
    destroyed = []

    class _Proxy:
        def destroy(self):
            destroyed.append("destroy")
            raise RuntimeError("connection already gone")

    mapping = mmap.mmap(-1, 64)
    held = memoryview(mapping)
    buffer = _ShmBuffer(_Proxy(), mapping)

    buffer.close()

    assert destroyed == ["destroy"]
    assert mapping.closed is False  # the live export blocked it, and that is fine
    held.release()
    mapping.close()


def test_a_buffer_release_closes_a_mapping_nothing_is_holding():
    mapping = mmap.mmap(-1, 64)

    class _Proxy:
        def destroy(self):
            return None

    _ShmBuffer(_Proxy(), mapping).close()

    assert mapping.closed is True
