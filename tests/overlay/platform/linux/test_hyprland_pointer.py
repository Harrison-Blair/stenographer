# SPDX-License-Identifier: GPL-3.0-or-later
"""Pointer placement from xdg-output geometry. Expected numbers are hand calculated."""

from __future__ import annotations

import logging
import socket
import threading
from pathlib import Path

import pytest
from pywayland.protocol.xdg_output_unstable_v1 import ZxdgOutputManagerV1

from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.overlay.platform.linux.backends.hyprland_pointer import (
    OutputGeometry,
    PointerPlacement,
    parse_cursor,
    place_under_pointer,
    query_pointer,
)
from stenographer.overlay.platform.linux.backends.layer_shell_backend import LayerShellBackend
from stenographer.overlay.platform.linux.backends.protocols.wlr_layer_shell_unstable_v1 import (
    ZwlrLayerSurfaceV1,
)
from stenographer.overlay.platform.linux.backends.registry_inventory import RegistryInventory
from stenographer.overlay.protocol.messages import StateMessage
from stenographer.overlay.rendering.render import render_overlay

# The rendered canvas at scale 1: 8 transparent px left of the pill, 5 above it.
_PILL_BOUNDS = (8, 5, 195, 48)

# The real layout, as xdg-output reports it on the development machine.
_REAL_LAYOUT = (
    OutputGeometry("DP-3", 0, 0, 2560, 1440),
    OutputGeometry("HDMI-A-1", 2560, -890, 1440, 2560),
    OutputGeometry("DP-2", -2560, 0, 2560, 1440),
)


@pytest.mark.parametrize(
    ("pointer", "expected"),
    [
        # No edge limit: canvas left = pointer x - 93 - 8; canvas top = y + 32 - 5.
        pytest.param((800, 700), ("DP-3", 727, 699), id="dp3"),
        pytest.param((-1200, 600), ("DP-2", 627, 1259), id="dp2-negative-origin"),
        pytest.param((3300, 1000), ("HDMI-A-1", 1917, 639), id="hdmi-rotated"),
        pytest.param((3300, -500), ("HDMI-A-1", 417, 639), id="hdmi-negative-y"),
        # The pill reaches each edge; the transparent canvas passes the side edges.
        pytest.param((5, 700), ("DP-3", 727, -8), id="left-edge"),
        pytest.param((2555, 700), ("DP-3", 727, 2365), id="right-edge"),
        pytest.param((3300, -889), ("HDMI-A-1", 28, 639), id="top-edge-is-below-the-gap"),
        pytest.param((800, 1435), ("DP-3", 1392, 699), id="bottom-edge"),
        pytest.param((2555, 1435), ("DP-3", 1392, 2365), id="bottom-right-corner"),
        pytest.param((3995, 1665), ("HDMI-A-1", 2512, 1245), id="rotated-corner"),
        # The first and the last column of a monitor belong to it.
        pytest.param((2560, 0), ("HDMI-A-1", 917, -8), id="first-column-of-hdmi"),
        pytest.param((2559, 0), ("DP-3", 27, 2365), id="last-column-of-dp3"),
    ],
)
def test_placement_on_the_real_monitor_layout(pointer, expected) -> None:
    assert place_under_pointer(pointer, _REAL_LAYOUT, _PILL_BOUNDS) == PointerPlacement(*expected)


@pytest.mark.parametrize(
    ("size", "pointer", "expected"),
    [
        # 3000 x 2000 at scale 1.5625: scale math gave 1875 x 1250 for this monitor.
        pytest.param((1920, 1280), (1900, 1000), (1027, 1725), id="1.5625-right-edge"),
        pytest.param((1920, 1280), (1800, 600), (627, 1699), id="1.5625-centered"),
        pytest.param((1920, 1280), (1000, 1200), (1227, 899), id="1.5625-keeps-the-gap"),
        # 2560 x 1440 at scale 4/3: scale math gave 1919 x 1079 and 1925 x 1083.
        pytest.param((1920, 1080), (1919, 1079), (1032, 1725), id="4/3-last-pixel"),
        pytest.param((1920, 1080), (1000, 1060), (1032, 899), id="4/3-bottom-edge"),
        # 3840 x 2160 at scale 5/3, turned by 90 degrees.
        pytest.param((1296, 2304), (1290, 2300), (2256, 1101), id="5/3-turned-corner"),
    ],
)
def test_placement_uses_the_reported_logical_size_directly(size, pointer, expected) -> None:
    monitors = (OutputGeometry("A", 0, 0, *size),)

    assert place_under_pointer(pointer, monitors, _PILL_BOUNDS) == PointerPlacement("A", *expected)


def test_the_border_at_x_1920_belongs_to_the_right_monitor() -> None:
    monitors = (
        OutputGeometry("LEFT", 0, 0, 1920, 1080),
        OutputGeometry("RIGHT", 1920, 0, 1920, 1080),
    )

    # The pill slides to the left edge of RIGHT: canvas margin -8.
    assert place_under_pointer((1922, 700), monitors, _PILL_BOUNDS) == PointerPlacement(
        "RIGHT", 727, -8
    )
    assert place_under_pointer((1919, 700), monitors, _PILL_BOUNDS) == PointerPlacement(
        "LEFT", 727, 1725
    )


def test_a_pointer_outside_every_monitor_has_no_placement() -> None:
    # DP-2 and DP-3 begin at y 0, and HDMI-A-1 begins at x 2560.
    assert place_under_pointer((100, -10), _REAL_LAYOUT, _PILL_BOUNDS) is None


def test_no_monitors_has_no_placement() -> None:
    assert place_under_pointer((100, 100), (), _PILL_BOUNDS) is None


def test_visible_pill_top_of_a_real_frame_is_32_below_the_pointer() -> None:
    frame = render_overlay(OverlayState.TRANSCRIBING)

    placement = place_under_pointer((3300, -500), _REAL_LAYOUT, frame.pill_bounds)

    assert placement is not None
    assert -890 + placement.margin_top + frame.pill_bounds[1] == -500 + 32
    assert 2560 + placement.margin_left + frame.pill_bounds[0] == 3300 - 93


def test_cursor_reply_as_the_live_socket_writes_it() -> None:
    assert parse_cursor(b'\n{\n    "x": 806,\n    "y": 1415\n}\n') == (806, 1415)


@pytest.mark.parametrize(
    "reply",
    [
        b"",
        b"unknown request",
        b"\xff\xfe",
        b"[]",
        b'{"x": 1}',
        b'{"x": "1", "y": 2}',
        b'{"x": true, "y": 2}',
    ],
)
def test_malformed_cursor_reply_is_rejected(reply: bytes) -> None:
    with pytest.raises(ValueError):
        parse_cursor(reply)


class _FakeHyprland:
    """A real Unix socket with Hyprland's one-request-per-connection behavior."""

    def __init__(self, path: Path, reply: bytes | None) -> None:
        path.parent.mkdir(parents=True)
        self.requests: list[bytes] = []
        self._reply = reply
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(path))
        self._server.listen()
        self._release = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while True:
            try:
                connection, _address = self._server.accept()
            except OSError:
                return
            with connection:
                self.requests.append(connection.recv(1024))
                if self._reply is None:
                    self._release.wait(5)
                else:
                    connection.sendall(self._reply)

    def close(self) -> None:
        self._release.set()
        self._server.shutdown(socket.SHUT_RDWR)
        self._server.close()
        self._thread.join(5)


_POINTER_REPLY = b'{"x": 800, "y": 700}'


@pytest.fixture
def hyprland(tmp_path, monkeypatch):
    """Start a fake server with the reply that the test gives, on the expected path."""
    servers = []
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "sig")

    def start(reply=_POINTER_REPLY):
        server = _FakeHyprland(tmp_path / "hypr" / "sig" / ".socket.sock", reply)
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.close()


def test_query_asks_the_socket_for_the_pointer_only(hyprland) -> None:
    server = hyprland()

    assert query_pointer() == (800, 700)
    assert server.requests == [b"j/cursorpos"]


@pytest.mark.parametrize("variable", ["HYPRLAND_INSTANCE_SIGNATURE", "XDG_RUNTIME_DIR"])
def test_outside_hyprland_there_is_no_query_and_no_log_line(
    hyprland, monkeypatch, caplog, variable: str
) -> None:
    server = hyprland()
    monkeypatch.delenv(variable)

    with caplog.at_level(logging.DEBUG):
        assert query_pointer() is None

    assert server.requests == []
    assert "hyprland_query_failed" not in caplog.text


def _assert_query_fails_with_a_log_line(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        assert query_pointer() is None
    assert "hyprland_query_failed" in caplog.text


@pytest.mark.usefixtures("hyprland")
def test_a_missing_socket_fails_with_a_log_line(caplog) -> None:
    _assert_query_fails_with_a_log_line(caplog)


@pytest.mark.parametrize("reply", [b"unknown request", b'{"x": 1}', b""])
def test_a_malformed_reply_fails_with_a_log_line(hyprland, caplog, reply: bytes) -> None:
    hyprland(reply)
    _assert_query_fails_with_a_log_line(caplog)


def test_a_silent_compositor_fails_with_a_log_line(hyprland, caplog) -> None:
    hyprland(None)
    _assert_query_fails_with_a_log_line(caplog)


class _Fake:
    """A Wayland proxy that records the requests of the backend."""

    def __init__(self, calls: dict[str, object] | None = None) -> None:
        self.calls = {} if calls is None else calls
        self.dispatcher: dict[str, object] = {}

    def __getattr__(self, name: str):
        def request(*args):
            self.calls[name] = args[0] if len(args) == 1 else args
            return self

        return request


class _FakeXdgOutputManager(_Fake):
    """Gives one new xdg-output proxy for each output, as the protocol does."""

    def __init__(self) -> None:
        super().__init__()
        self.xdg_outputs: dict[object, _Fake] = {}

    def get_xdg_output(self, output):
        self.xdg_outputs[output] = _Fake()
        return self.xdg_outputs[output]


class _FakeRegistry:
    def __init__(self, calls: dict[str, object]) -> None:
        self.calls = calls
        self.binds: list[tuple[int, object, int]] = []
        self.manager = _FakeXdgOutputManager()

    def bind(self, name, interface, version):
        self.binds.append((name, interface, version))
        return self.manager if interface is ZxdgOutputManagerV1 else _Fake(self.calls)


def _backend() -> tuple[LayerShellBackend, dict[str, object]]:
    """A backend with its display replaced, which is the only external part here."""
    calls: dict[str, object] = {}
    backend = LayerShellBackend.__new__(LayerShellBackend)
    super(LayerShellBackend, backend).__init__()
    backend._compositor = _Fake(calls)
    backend._layer_shell = _Fake(calls)
    backend._fractional_manager = None
    backend._viewporter = None
    backend._fractional_scale = None
    backend._viewport = None
    backend._surface = None
    backend._layer_surface = None
    backend._registry = _FakeRegistry(calls)
    backend._inventory = RegistryInventory()
    backend._initialized = False
    backend._lost = False
    backend._outputs = {}
    backend._output_scales = {}
    backend._xdg_output_manager = None
    backend._xdg_outputs = {}
    backend._entered_outputs = set()
    backend._buffers = {}
    backend._configured = False
    backend._render_pending = False
    backend._preferred_scale_120 = None
    return backend, calls


def _advertise_and_bind_globals(backend: LayerShellBackend, *extra: tuple[str, int]) -> None:
    required = (("wl_compositor", 4), ("wl_shm", 1), ("zwlr_layer_shell_v1", 4))
    for name, (interface, version) in enumerate((*required, *extra), start=1):
        backend._inventory.add(name, interface, version)
    backend._bind_globals()
    backend._initialized = True


def _report(backend, wl_name, x, y, width, height) -> object:
    """Send the logical geometry events of one bound output; return its wl_output."""
    output = backend._outputs[wl_name][0]
    xdg_output = backend._registry.manager.xdg_outputs[output]
    xdg_output.dispatcher["logical_position"](xdg_output, x, y)
    xdg_output.dispatcher["logical_size"](xdg_output, width, height)
    return output


def _backend_with_dp3_and_dp2() -> tuple[LayerShellBackend, dict[str, object], object, object]:
    backend, calls = _backend()
    _advertise_and_bind_globals(
        backend, ("wl_output", 3), ("wl_output", 3), ("zxdg_output_manager_v1", 3)
    )
    dp3 = _report(backend, 4, 0, 0, 2560, 1440)
    dp2 = _report(backend, 5, -2560, 0, 2560, 1440)
    return backend, calls, dp3, dp2


def _show(backend: LayerShellBackend, generation: int, state: OverlayState) -> None:
    backend._dispatch(StateMessage(generation, state))


@pytest.mark.parametrize(("advertised", "bound"), [(1, 1), (3, 3), (7, 3)])
def test_the_manager_binds_up_to_version_3(advertised: int, bound: int) -> None:
    backend, _calls = _backend()

    _advertise_and_bind_globals(backend, ("zxdg_output_manager_v1", advertised))

    assert (4, ZxdgOutputManagerV1, bound) in backend._registry.binds
    assert backend._xdg_output_manager is backend._registry.manager


def test_an_output_advertised_before_the_manager_gets_an_xdg_output() -> None:
    backend, _calls = _backend()

    _advertise_and_bind_globals(backend, ("wl_output", 3), ("zxdg_output_manager_v1", 3))

    output = backend._outputs[4][0]
    assert list(backend._registry.manager.xdg_outputs) == [output]


def test_an_output_added_later_gets_an_xdg_output(hyprland) -> None:
    hyprland(b'{"x": 5000, "y": 100}')
    backend, calls = _backend()
    _advertise_and_bind_globals(backend, ("wl_output", 3), ("zxdg_output_manager_v1", 3))
    _report(backend, 4, 0, 0, 2560, 1440)

    backend._on_global(None, 9, "wl_output", 3)
    added = _report(backend, 9, 4000, 0, 1920, 1080)
    _show(backend, 1, OverlayState.RECORDING)

    # Canvas left = 5000 - 93 - 8 - 4000; canvas top = 100 + 32 - 5.
    assert calls["get_layer_surface"][1] is added
    assert calls["set_margin"] == (127, 0, 0, 899)


def test_a_removed_output_destroys_its_xdg_output_and_leaves_the_layout(hyprland) -> None:
    hyprland()
    backend, calls, dp3, dp2 = _backend_with_dp3_and_dp2()
    xdg_output = backend._registry.manager.xdg_outputs[dp3]

    backend._on_global_remove(None, 4)

    assert "destroy" in xdg_output.calls
    assert dp3 not in backend._xdg_outputs
    # The pointer at (800, 700) was on the removed DP-3 and is now on no monitor.
    _show(backend, 1, OverlayState.RECORDING)
    assert calls["get_layer_surface"][1] is None
    assert dp2 in backend._xdg_outputs


def test_close_destroys_each_xdg_output_and_the_manager() -> None:
    backend, _calls, dp3, _dp2 = _backend_with_dp3_and_dp2()
    backend._shm = None
    backend._display = _Fake()
    manager = backend._registry.manager
    xdg_output = manager.xdg_outputs[dp3]

    backend._close()

    assert "destroy" in xdg_output.calls
    assert "destroy" in manager.calls
    assert backend._xdg_outputs == {}


def test_surface_opens_at_the_pointer_on_its_output(hyprland) -> None:
    hyprland()
    backend, calls, dp3, _dp2 = _backend_with_dp3_and_dp2()

    _show(backend, 1, OverlayState.RECORDING)

    assert calls["get_layer_surface"][1] is dp3
    assert calls["set_anchor"] == ZwlrLayerSurfaceV1.anchor.top | ZwlrLayerSurfaceV1.anchor.left
    assert calls["set_margin"] == (727, 0, 0, 699)
    assert calls["set_exclusive_zone"] == -1
    assert calls["set_size"] == (204, 60)


def test_placement_happens_once_for_each_hidden_to_visible_change(hyprland) -> None:
    server = hyprland()
    backend, _calls, _dp3, _dp2 = _backend_with_dp3_and_dp2()

    _show(backend, 1, OverlayState.RECORDING)
    _show(backend, 2, OverlayState.TRANSCRIBING)
    _show(backend, 3, OverlayState.APPLIED)
    assert server.requests == [b"j/cursorpos"]

    _show(backend, 4, OverlayState.HIDDEN)
    assert len(server.requests) == 1
    _show(backend, 5, OverlayState.RECORDING)
    assert len(server.requests) == 2


def test_the_next_show_uses_the_geometry_reported_since_the_last_one(hyprland) -> None:
    hyprland()
    backend, calls, dp3, _dp2 = _backend_with_dp3_and_dp2()

    _report(backend, 4, 100, 50, 2560, 1440)
    _show(backend, 1, OverlayState.RECORDING)

    # Canvas left = 800 - 93 - 8 - 100; canvas top = 700 + 32 - 5 - 50.
    assert calls["get_layer_surface"][1] is dp3
    assert calls["set_margin"] == (677, 0, 0, 599)


def _assert_bottom_center(calls: dict[str, object]) -> None:
    assert calls["get_layer_surface"][1] is None
    assert calls["set_anchor"] == ZwlrLayerSurfaceV1.anchor.bottom
    # The canvas has 12 px below the pill, so 20 + 12 is the EDGE_OFFSET of 32.
    assert calls["set_margin"] == (0, 0, 20, 0)
    assert calls["set_exclusive_zone"] == 0


def test_without_hyprland_the_surface_uses_bottom_center(monkeypatch) -> None:
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
    backend, calls, _dp3, _dp2 = _backend_with_dp3_and_dp2()

    _show(backend, 1, OverlayState.RECORDING)

    _assert_bottom_center(calls)


def test_a_failed_query_uses_bottom_center(hyprland, caplog) -> None:
    hyprland(b"not json")
    backend, calls, _dp3, _dp2 = _backend_with_dp3_and_dp2()

    with caplog.at_level(logging.WARNING):
        _show(backend, 1, OverlayState.RECORDING)

    _assert_bottom_center(calls)
    assert "hyprland_query_failed" in caplog.text


def test_a_compositor_without_the_manager_uses_bottom_center(hyprland) -> None:
    hyprland()
    backend, calls = _backend()
    _advertise_and_bind_globals(backend, ("wl_output", 3))

    assert backend._xdg_output_manager is None
    _show(backend, 1, OverlayState.RECORDING)

    _assert_bottom_center(calls)


@pytest.mark.parametrize("event", ["logical_position", "logical_size"])
def test_an_output_with_incomplete_geometry_is_not_used(hyprland, event: str) -> None:
    hyprland()
    backend, calls = _backend()
    _advertise_and_bind_globals(backend, ("wl_output", 3), ("zxdg_output_manager_v1", 3))
    output = backend._outputs[4][0]
    xdg_output = backend._registry.manager.xdg_outputs[output]

    xdg_output.dispatcher[event](xdg_output, 0, 2560)
    _show(backend, 1, OverlayState.RECORDING)

    _assert_bottom_center(calls)
