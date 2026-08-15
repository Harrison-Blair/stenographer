# SPDX-License-Identifier: GPL-3.0-or-later
"""Real XWayland surface smoke; no display or process mocking."""

from __future__ import annotations

import os
import queue
import threading
import time

import pytest

pytestmark = pytest.mark.integration

if os.environ.get("STENOGRAPHER_INTEGRATION") != "1":
    pytest.skip("integration suite requires STENOGRAPHER_INTEGRATION=1", allow_module_level=True)

from Xlib import X, Xatom  # noqa: E402
from Xlib import display as xdisplay  # noqa: E402
from Xlib.ext import shape  # noqa: E402

from stenographer.overlay_x11 import X11OverlayBackend, X11Unavailable  # noqa: E402
from stenographer.status import (  # noqa: E402
    Command,
    CommandMessage,
    OverlayState,
    StateMessage,
    encode_message,
)


def _find_window(display, expected_id: int):
    for window in display.screen().root.query_tree().children:
        if window.id == expected_id:
            return window
    return None


def _wait_for_backend_window_id(backend: X11OverlayBackend, timeout: float = 3.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        window = backend._window
        if window is not None:
            return window.id
        time.sleep(0.02)
    pytest.fail("XWayland backend did not create its overlay window")


def _wait_for_window(display, expected_id: int, *, present: bool, timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        display.sync()
        window = _find_window(display, expected_id)
        if (window is not None) is present:
            return window
        time.sleep(0.02)
    pytest.fail(f"XWayland overlay window did not become {'visible' if present else 'hidden'}")


def test_real_xwayland_window_is_click_through_and_updates_in_place():
    read_fd, write_fd = os.pipe()
    ready: queue.Queue[X11OverlayBackend | BaseException] = queue.Queue(maxsize=1)
    failures: queue.Queue[BaseException] = queue.Queue(maxsize=1)

    def serve() -> None:
        backend = None
        announced = False
        with os.fdopen(read_fd, "rb", buffering=0) as input_stream:
            try:
                backend = X11OverlayBackend()
                ready.put(backend)
                announced = True
                backend.run(input_stream)
            except BaseException as exc:
                (failures if announced else ready).put(exc)
            finally:
                if backend is not None:
                    backend.close()

    thread = threading.Thread(target=serve, name="test-xwayland-overlay")
    thread.start()
    result = ready.get(timeout=3)
    if isinstance(result, X11Unavailable):
        os.close(write_fd)
        thread.join(timeout=3)
        pytest.skip(f"XWayland unavailable: {result.reason.value}")
    if isinstance(result, BaseException):
        os.close(write_fd)
        thread.join(timeout=3)
        raise result

    observer = xdisplay.Display()
    try:
        os.write(
            write_fd,
            encode_message(StateMessage(0, OverlayState.RECORDING)).encode("ascii"),
        )
        window_id = _wait_for_backend_window_id(result)
        window = _wait_for_window(observer, window_id, present=True)

        name = window.get_full_property(
            observer.intern_atom("_NET_WM_NAME"), observer.intern_atom("UTF8_STRING")
        )
        assert name is not None
        assert bytes(name.value) == b"Stenographer"

        attributes = window.get_attributes()
        assert attributes.override_redirect == 1
        assert attributes.visual == result._visual.visual_id
        assert result._pict_format is not None
        assert result._pict_format.alpha_shift == 24
        assert result._pict_format.alpha_mask == 0xFF
        assert window.get_wm_hints()["input"] == 0
        assert not window.shape_get_rectangles(shape.SK.Input).rectangles

        window_type = window.get_full_property(
            observer.intern_atom("_NET_WM_WINDOW_TYPE"), Xatom.ATOM
        )
        assert window_type is not None
        assert list(window_type.value) == [observer.intern_atom("_NET_WM_WINDOW_TYPE_NOTIFICATION")]

        # Mutter normalizes override-redirect properties asynchronously during
        # map. Check the settled window, after both bounded helper reassertions.
        time.sleep(1.1)
        window = _wait_for_window(observer, window_id, present=True)
        assert window.id == window_id
        state = window.get_full_property(observer.intern_atom("_NET_WM_STATE"), Xatom.ATOM)
        assert state is not None
        state_atoms = set(state.value)
        assert observer.intern_atom("_NET_WM_STATE_ABOVE") in state_atoms
        assert observer.intern_atom("_NET_WM_STATE_SKIP_TASKBAR") in state_atoms
        assert observer.intern_atom("_NET_WM_STATE_SKIP_PAGER") in state_atoms
        viewable_children = []
        for child in observer.screen().root.query_tree().children:
            try:
                if child.get_attributes().map_state == X.IsViewable:
                    viewable_children.append(child)
            except Exception:
                continue
        assert viewable_children
        assert viewable_children[-1].id == window_id

        placement = result._placement
        assert placement is not None
        monitor = placement.monitor
        geometry = window.get_geometry()
        assert abs((geometry.x + geometry.width // 2) - (monitor.x + monitor.width // 2)) <= 1
        assert monitor.y <= geometry.y
        assert geometry.y + geometry.height <= monitor.y + monitor.height

        os.write(
            write_fd,
            encode_message(StateMessage(1, OverlayState.TRANSCRIBING)).encode("ascii"),
        )
        assert _wait_for_window(observer, window_id, present=True).id == window_id

        os.write(
            write_fd,
            encode_message(StateMessage(2, OverlayState.HIDDEN)).encode("ascii"),
        )
        _wait_for_window(observer, window_id, present=False)
        os.write(write_fd, encode_message(CommandMessage(Command.SHUTDOWN)).encode("ascii"))
    finally:
        os.close(write_fd)
        observer.close()
        thread.join(timeout=3)
    assert not thread.is_alive()
    if not failures.empty():
        raise failures.get_nowait()
