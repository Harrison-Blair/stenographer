# SPDX-License-Identifier: GPL-3.0-or-later
"""Pointer placement from Hyprland data. Expected numbers are hand calculated."""

from __future__ import annotations

import json
import logging
import socket
import threading
from pathlib import Path

import pytest

from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.overlay.platform.linux.backends.hyprland_pointer import (
    HyprlandMonitor,
    PointerPlacement,
    parse_cursor,
    parse_monitors,
    place_under_pointer,
    query_pointer_placement,
)
from stenographer.overlay.platform.linux.backends.layer_shell_backend import LayerShellBackend
from stenographer.overlay.platform.linux.backends.protocols.wlr_layer_shell_unstable_v1 import (
    ZwlrLayerSurfaceV1,
)
from stenographer.overlay.protocol.messages import StateMessage
from stenographer.overlay.rendering.render import render_overlay

# The rendered canvas at scale 1: 8 transparent px left of the pill, 5 above it.
_PILL_BOUNDS = (8, 5, 195, 48)


def _raw_monitor(name, x, y, width=2560, height=1440, scale=1, transform=0) -> dict:
    return {
        "id": 1,
        "name": name,
        "width": width,
        "height": height,
        "x": x,
        "y": y,
        "scale": scale,
        "transform": transform,
        "focused": False,
    }


_REAL_LAYOUT = [
    _raw_monitor("DP-3", 0, 0),
    _raw_monitor("HDMI-A-1", 2560, -890, transform=3),
    _raw_monitor("DP-2", -2560, 0),
]


def _monitors() -> tuple[HyprlandMonitor, ...]:
    return parse_monitors(json.dumps(_REAL_LAYOUT).encode())


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
        # The rotated logical size is 1440 x 2560: x ends at 4000, y ends at 1670.
        pytest.param((3995, 1665), ("HDMI-A-1", 2512, 1245), id="rotated-corner"),
        # The first and the last column of a monitor belong to it.
        pytest.param((2560, 0), ("HDMI-A-1", 917, -8), id="first-column-of-hdmi"),
        pytest.param((2559, 0), ("DP-3", 27, 2365), id="last-column-of-dp3"),
    ],
)
def test_placement_on_the_real_monitor_layout(pointer, expected) -> None:
    assert place_under_pointer(pointer, _monitors(), _PILL_BOUNDS) == PointerPlacement(*expected)


@pytest.mark.parametrize(
    ("monitor", "pointer", "expected"),
    [
        # 3840 x 2160 at scale 2 is 1920 x 1080 logical.
        pytest.param(
            _raw_monitor("A", 0, 0, 3840, 2160, 2), (1900, 1070), (1032, 1725), id="scale-2"
        ),
        # 2560 x 1600 at scale 1.5 is 1706.67 x 1066.67 logical: the size rounds down.
        pytest.param(
            _raw_monitor("A", 100, 50, 2560, 1600, 1.5), (1800, 1110), (1018, 1511), id="scale-1.5"
        ),
        # Transform 1 also turns the mode: 3840 x 2160 at scale 2 is 1080 x 1920.
        pytest.param(
            _raw_monitor("A", 0, 0, 3840, 2160, 2, 1),
            (1075, 1900),
            (1872, 885),
            id="turned-scale-2",
        ),
    ],
)
def test_placement_uses_the_logical_monitor_size(monitor, pointer, expected) -> None:
    monitors = parse_monitors(json.dumps([monitor]).encode())
    assert place_under_pointer(pointer, monitors, _PILL_BOUNDS) == PointerPlacement("A", *expected)


def test_a_pointer_outside_every_monitor_has_no_placement() -> None:
    # DP-2 and DP-3 begin at y 0, and HDMI-A-1 begins at x 2560.
    assert place_under_pointer((100, -10), _monitors(), _PILL_BOUNDS) is None


def test_visible_pill_top_of_a_real_frame_is_32_below_the_pointer() -> None:
    frame = render_overlay(OverlayState.TRANSCRIBING)

    placement = place_under_pointer((3300, -500), _monitors(), frame.pill_bounds)

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


@pytest.mark.parametrize(
    "reply",
    [
        b"",
        b"{}",
        b"[1]",
        b'[{"name": "A"}]',
        json.dumps([_raw_monitor("A", 0, 0, scale=0)]).encode(),
        json.dumps([_raw_monitor("A", 0, 0, scale="1")]).encode(),
        json.dumps([_raw_monitor(7, 0, 0)]).encode(),
        json.dumps([_raw_monitor("A", 0.5, 0)]).encode(),
    ],
)
def test_malformed_monitors_reply_is_rejected(reply: bytes) -> None:
    with pytest.raises(ValueError):
        parse_monitors(reply)


class _FakeHyprland:
    """A real Unix socket with Hyprland's one-request-per-connection behavior."""

    def __init__(self, path: Path, replies: dict[bytes, bytes | None]) -> None:
        path.parent.mkdir(parents=True)
        self.requests: list[bytes] = []
        self._replies = replies
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
                request = connection.recv(1024)
                self.requests.append(request)
                reply = self._replies[request]
                if reply is None:
                    self._release.wait(5)
                else:
                    connection.sendall(reply)

    def close(self) -> None:
        self._release.set()
        self._server.shutdown(socket.SHUT_RDWR)
        self._server.close()
        self._thread.join(5)


_GOOD_REPLIES = {
    b"j/cursorpos": b'{"x": 800, "y": 700}',
    b"j/monitors": json.dumps(_REAL_LAYOUT).encode(),
}


@pytest.fixture
def hyprland(tmp_path, monkeypatch):
    """Start a fake server for the replies that the test gives, on the expected path."""
    servers = []
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "sig")

    def start(replies):
        server = _FakeHyprland(tmp_path / "hypr" / "sig" / ".socket.sock", replies)
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.close()


def test_query_reads_both_replies_from_the_socket(hyprland) -> None:
    server = hyprland(_GOOD_REPLIES)

    assert query_pointer_placement(_PILL_BOUNDS) == PointerPlacement("DP-3", 727, 699)
    assert server.requests == [b"j/cursorpos", b"j/monitors"]


@pytest.mark.parametrize("variable", ["HYPRLAND_INSTANCE_SIGNATURE", "XDG_RUNTIME_DIR"])
def test_outside_hyprland_there_is_no_query_and_no_log_line(
    hyprland, monkeypatch, caplog, variable: str
) -> None:
    server = hyprland(_GOOD_REPLIES)
    monkeypatch.delenv(variable)

    with caplog.at_level(logging.DEBUG):
        assert query_pointer_placement(_PILL_BOUNDS) is None

    assert server.requests == []
    assert "hyprland_query_failed" not in caplog.text


def _assert_query_fails_with_a_log_line(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        assert query_pointer_placement(_PILL_BOUNDS) is None
    assert "hyprland_query_failed" in caplog.text


@pytest.mark.usefixtures("hyprland")
def test_a_missing_socket_fails_with_a_log_line(caplog) -> None:
    _assert_query_fails_with_a_log_line(caplog)


@pytest.mark.parametrize(
    "replies",
    [
        pytest.param({**_GOOD_REPLIES, b"j/cursorpos": b"unknown request"}, id="cursor-text"),
        pytest.param({**_GOOD_REPLIES, b"j/monitors": b'[{"name": "A"}]'}, id="monitor-fields"),
        pytest.param({**_GOOD_REPLIES, b"j/monitors": b""}, id="empty-reply"),
    ],
)
def test_a_malformed_reply_fails_with_a_log_line(hyprland, caplog, replies) -> None:
    hyprland(replies)
    _assert_query_fails_with_a_log_line(caplog)


def test_a_silent_compositor_fails_with_a_log_line(hyprland, caplog) -> None:
    hyprland({**_GOOD_REPLIES, b"j/cursorpos": None})
    _assert_query_fails_with_a_log_line(caplog)


class _Fake:
    """A Wayland proxy that records the requests of the backend."""

    def __init__(self, calls: dict[str, object]) -> None:
        self.calls = calls
        self.dispatcher: dict[str, object] = {}

    def __getattr__(self, name: str):
        def request(*args):
            self.calls[name] = args[0] if len(args) == 1 else args
            return self

        return request


def _backend(names: dict[object, str]) -> tuple[LayerShellBackend, dict[str, object]]:
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
    backend._output_names = names
    backend._entered_outputs = set()
    backend._buffers = {}
    backend._configured = False
    backend._render_pending = False
    backend._preferred_scale_120 = None
    return backend, calls


def _show(backend: LayerShellBackend, generation: int, state: OverlayState) -> None:
    backend._dispatch(StateMessage(generation, state))


def test_surface_opens_at_the_pointer_on_the_named_output(hyprland) -> None:
    hyprland(_GOOD_REPLIES)
    other, dp3 = object(), object()
    backend, calls = _backend({other: "DP-2", dp3: "DP-3"})

    _show(backend, 1, OverlayState.RECORDING)

    assert calls["get_layer_surface"][1] is dp3
    assert calls["set_anchor"] == ZwlrLayerSurfaceV1.anchor.top | ZwlrLayerSurfaceV1.anchor.left
    assert calls["set_margin"] == (727, 0, 0, 699)
    assert calls["set_exclusive_zone"] == -1
    assert calls["set_size"] == (204, 60)


def test_placement_happens_once_for_each_hidden_to_visible_change(hyprland) -> None:
    server = hyprland(_GOOD_REPLIES)
    backend, _calls = _backend({object(): "DP-3"})

    _show(backend, 1, OverlayState.RECORDING)
    _show(backend, 2, OverlayState.TRANSCRIBING)
    _show(backend, 3, OverlayState.APPLIED)
    assert server.requests == [b"j/cursorpos", b"j/monitors"]

    _show(backend, 4, OverlayState.HIDDEN)
    assert len(server.requests) == 2
    _show(backend, 5, OverlayState.RECORDING)
    assert len(server.requests) == 4


def _assert_bottom_center(calls: dict[str, object]) -> None:
    assert calls["get_layer_surface"][1] is None
    assert calls["set_anchor"] == ZwlrLayerSurfaceV1.anchor.bottom
    # The canvas has 12 px below the pill, so 20 + 12 is the EDGE_OFFSET of 32.
    assert calls["set_margin"] == (0, 0, 20, 0)
    assert calls["set_exclusive_zone"] == 0


def test_without_hyprland_the_surface_uses_bottom_center(monkeypatch) -> None:
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
    backend, calls = _backend({object(): "DP-3"})

    _show(backend, 1, OverlayState.RECORDING)

    _assert_bottom_center(calls)


def test_a_failed_query_uses_bottom_center(hyprland, caplog) -> None:
    hyprland({**_GOOD_REPLIES, b"j/monitors": b"not json"})
    backend, calls = _backend({object(): "DP-3"})

    with caplog.at_level(logging.WARNING):
        _show(backend, 1, OverlayState.RECORDING)

    _assert_bottom_center(calls)
    assert "hyprland_query_failed" in caplog.text


def test_no_output_with_the_monitor_name_uses_bottom_center(hyprland, caplog) -> None:
    hyprland(_GOOD_REPLIES)
    backend, calls = _backend({object(): "DP-2"})

    with caplog.at_level(logging.INFO):
        _show(backend, 1, OverlayState.RECORDING)

    _assert_bottom_center(calls)
    assert "pointer_output_unmatched" in caplog.text


@pytest.mark.parametrize(("advertised", "bound"), [(3, 3), (4, 4), (7, 4)])
def test_outputs_bind_the_version_that_has_the_name_event(advertised: int, bound: int) -> None:
    binds = []

    class Registry:
        def bind(self, name, _interface, version):
            binds.append((name, version))
            return _Fake({})

    backend, _calls = _backend({})
    backend._registry = Registry()
    backend._outputs = {}
    backend._output_scales = {}

    backend._bind_output(9, advertised)

    assert binds == [(9, bound)]
    output = backend._outputs[9][0]
    output.dispatcher["name"](output, "DP-3")
    assert backend._output_named("DP-3") is output
