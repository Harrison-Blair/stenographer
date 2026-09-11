# SPDX-License-Identifier: GPL-3.0-or-later
"""Scaffolding shared by both helper-side overlay backends.

The pure helpers come first. The serve loop follows, driven through a test
subclass whose "display connection" is a second real ``os.pipe`` and whose
parent stream is a third: the loop's job is to turn bytes on a descriptor into
surface work, so anything short of real descriptors would test nothing.
"""

from __future__ import annotations

import ast
import os
import pathlib
import time

import pytest

from stenographer.lib.contracts.constants import SPECTRUM_BANDS
from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.overlay.platform.linux.backends import helper_backend as base
from stenographer.overlay.platform.linux.backends.base import next_timeout, probe_backend
from stenographer.overlay.platform.linux.backends.errors import BackendUnavailableError
from stenographer.overlay.protocol.backend import Backend
from stenographer.overlay.protocol.codec import encode_message
from stenographer.overlay.protocol.command import Command
from stenographer.overlay.protocol.errors import ProtocolError
from stenographer.overlay.protocol.messages import (
    CommandMessage,
    LoadingActivityMessage,
    SpectrumMessage,
    StateMessage,
)
from stenographer.overlay.protocol.unavailablereason import UnavailableReason
from stenographer.overlay.rendering.constants import LOADING_FRAME_INTERVAL


def test_no_pending_deadline_blocks_the_selector_indefinitely() -> None:
    assert next_timeout() is None
    assert next_timeout(None, None) is None


def test_the_earliest_deadline_wins_and_a_due_one_is_not_mistaken_for_idle() -> None:
    assert next_timeout(0.75, None, 0.1) == 0.1
    assert next_timeout(None, 0.0, 2.5) == 0.0


def test_probe_translates_a_fixed_reason_and_never_leaves_a_connection_open() -> None:
    closed = []

    class _Unusable:
        def __init__(self) -> None:
            raise BackendUnavailableError(UnavailableReason.NO_X_DISPLAY)

        def close(self) -> None:  # pragma: no cover - never constructed
            closed.append("unusable")

    class _Usable:
        def close(self) -> None:
            closed.append("usable")

    assert probe_backend(_Unusable) is UnavailableReason.NO_X_DISPLAY
    assert probe_backend(_Usable) is None
    assert closed == ["usable"]


def test_probe_lets_an_unexpected_construction_failure_reach_the_registry() -> None:
    class _Broken:
        def __init__(self) -> None:
            raise RuntimeError("generated bindings missing")

        def close(self) -> None:  # pragma: no cover - never constructed
            raise AssertionError

    try:
        probe_backend(_Broken)
    except RuntimeError:
        return
    raise AssertionError("probe swallowed a non-reason failure")


def test_the_fixed_reason_is_the_whole_error_text() -> None:
    error = BackendUnavailableError(UnavailableReason.REQUIRED_GLOBALS_MISSING)

    assert error.reason is UnavailableReason.REQUIRED_GLOBALS_MISSING
    assert str(error) == "required_wayland_globals_missing"


def _self_calls(source: str, method: str) -> set[str]:
    """Names the given base method invokes as ``self.<name>(...)``."""
    tree = ast.parse(source)
    body = next(
        node
        for cls in ast.walk(tree)
        if isinstance(cls, ast.ClassDef) and cls.name == "HelperBackend"
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == method
    )
    return {
        node.func.attr
        for node in ast.walk(body)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "self"
    }


def test_every_hook_the_shared_loop_calls_exists_on_the_base() -> None:
    """A hook the loop calls but never declares raises only at runtime.

    Seen to FAIL with ``_after_events`` declared on the Wayland backend but
    absent from the base: the XWayland helper reached its first state message
    and died with AttributeError, which no unit test could have caught.
    """
    source = pathlib.Path(base.__file__).read_text(encoding="utf-8")
    called = set()
    for method in ("run", "_dispatch", "_select_timeout", "_on_timers", "close", "_frame"):
        called |= _self_calls(source, method)

    missing = sorted(name for name in called if not hasattr(base.HelperBackend, name))

    assert called, "the loop was expected to delegate to hooks"
    assert not missing, missing


def test_both_backends_implement_every_display_specific_hook() -> None:
    pytest.importorskip("pywayland")
    pytest.importorskip("Xlib")
    from stenographer.overlay.platform.linux.backends.layer_shell_backend import LayerShellBackend
    from stenographer.overlay.platform.linux.backends.x11_overlay_backend import X11OverlayBackend

    required = ("_display_fd", "_draw", "_teardown", "_on_display_readable", "_close")
    for backend in (LayerShellBackend, X11OverlayBackend):
        inherited = [
            name for name in required if getattr(backend, name) is getattr(base.HelperBackend, name)
        ]
        assert not inherited, (backend.__name__, inherited)
        assert isinstance(backend.backend, Backend)


class _LoopBackend(base.HelperBackend):
    """A display-less stand-in: a second real pipe plays the display connection.

    Only the six hooks the shared loop declares are overridden, so the base's
    own no-op adjustments (``_before_select``, ``_extra_timeouts``,
    ``_on_extra_timers``, ``_after_events``) run for real on every turn.
    """

    backend = Backend.XWAYLAND

    def __init__(self, display_fd: int) -> None:
        super().__init__()
        self._fd = display_fd
        self.events: list[str] = []
        self.closes = 0

    def _display_fd(self) -> int:
        return self._fd

    def _draw(self) -> None:
        self.events.append("draw")

    def _repaint(self) -> None:
        self.events.append("repaint")

    def _teardown(self) -> None:
        self.events.append("teardown")

    def _on_display_readable(self, mask: int) -> None:
        os.read(self._fd, 4096)
        self.events.append("display")

    def _close(self) -> None:
        self.closes += 1


class _TimedBackend(_LoopBackend):
    """A backend with a deadline of its own, the way the X11 one reasserts."""

    def __init__(self, display_fd: int) -> None:
        super().__init__(display_fd)
        self.extra: tuple[float | None, ...] = ()
        self.extra_timers = 0

    def _extra_timeouts(self, now: float) -> tuple[float | None, ...]:
        return self.extra

    def _on_extra_timers(self) -> None:
        self.extra_timers += 1


class _Wire:
    """One backend plus the two real pipes it is driven through.

    Descriptor ownership is explicit: ``stream`` owns the read end of the
    parent pipe (``os.fdopen`` took it over), and this object owns the other
    three. Nothing is closed twice, so a genuine double close would raise.
    """

    def __init__(self, backend, stream, input_write: int, display_read: int, display_write: int):
        self.backend = backend
        self.stream = stream
        self.display_write = display_write
        self._input_write = input_write
        self._display_read = display_read
        self._input_open = True

    def send(self, *messages) -> None:
        for message in messages:
            self.send_raw(encode_message(message).encode("ascii"))

    def send_raw(self, payload: bytes) -> None:
        os.write(self._input_write, payload)

    def end_input(self) -> None:
        """Close the parent's end so the serve loop reaches EOF."""
        if self._input_open:
            self._input_open = False
            os.close(self._input_write)

    def dispose(self) -> None:
        self.end_input()
        self.stream.close()
        os.close(self._display_read)
        os.close(self.display_write)


@pytest.fixture
def loop():
    """A backend wired to two real pipes: the parent stream and the display."""
    if os.name != "posix":
        pytest.skip("the Linux backend loop selects on POSIX pipe descriptors")
    wires: list[_Wire] = []

    def build(factory=_LoopBackend) -> _Wire:
        input_read, input_write = os.pipe()
        display_read, display_write = os.pipe()
        wire = _Wire(
            factory(display_read),
            os.fdopen(input_read, "rb", buffering=0),
            input_write,
            display_read,
            display_write,
        )
        wires.append(wire)
        return wire

    try:
        yield build
    finally:
        for wire in wires:
            wire.dispose()


def test_the_shared_loop_turns_parent_records_into_surface_work(loop) -> None:
    """The reducer decides, the loop delegates: a state change draws, a frame
    only repaints, and hiding tears the surface down without ending the session.
    """
    wire = loop()
    wire.send(
        StateMessage(0, OverlayState.RECORDING),
        SpectrumMessage(0, 0, (7,) * SPECTRUM_BANDS),
        StateMessage(1, OverlayState.HIDDEN),
    )
    wire.end_input()

    wire.backend.run(wire.stream)

    assert wire.backend.events == ["draw", "repaint", "teardown"]
    assert wire.backend._state is OverlayState.HIDDEN


def test_the_shutdown_command_stops_the_loop_before_the_next_record(loop) -> None:
    """Seen to matter for an orderly exit: anything dispatched after shutdown
    would paint onto a surface the helper is about to release.
    """
    wire = loop()
    wire.send(
        CommandMessage(Command.SHUTDOWN),
        StateMessage(0, OverlayState.RECORDING),
    )
    wire.end_input()

    wire.backend.run(wire.stream)

    assert wire.backend.events == []


def test_a_readable_display_connection_is_serviced_in_the_same_turn(loop) -> None:
    wire = loop()
    os.write(wire.display_write, b"display event")
    wire.send(StateMessage(0, OverlayState.TRANSCRIBING))
    wire.end_input()

    wire.backend.run(wire.stream)

    assert wire.backend.events.count("display") == 1
    assert "draw" in wire.backend.events


def test_a_truncated_final_record_is_a_protocol_error_not_a_quiet_exit(loop) -> None:
    wire = loop()
    wire.send_raw(b'{"v":4,"type":"state","generation":0')
    wire.end_input()

    with pytest.raises(ProtocolError, match="mid-record"):
        wire.backend.run(wire.stream)


def test_an_idle_backend_lets_the_selector_block_indefinitely(loop) -> None:
    backend = loop().backend

    assert backend._select_timeout() is None


def test_a_backend_deadline_and_the_loading_pulse_share_one_selector_wait(loop) -> None:
    """Both are folded into one wait, so neither can be missed by the other."""
    backend = loop(_TimedBackend).backend
    backend._reducer.state = OverlayState.TRANSCRIBING
    backend._reducer.pulse.set_active(True, time.monotonic())
    backend._reducer.pulse.arm(time.monotonic() + 10.0)

    pulse_only = backend._select_timeout()
    backend.extra = (0.25, None)
    both = backend._select_timeout()

    assert pulse_only == pytest.approx(10.0 + LOADING_FRAME_INTERVAL, abs=0.5)
    assert both == pytest.approx(0.25, abs=0.05)


def test_a_due_loading_frame_repaints_and_rearms_the_cadence(loop) -> None:
    backend = loop(_TimedBackend).backend
    backend._reducer.state = OverlayState.TRANSCRIBING
    backend._reducer.pulse.set_active(True, time.monotonic())
    backend._reducer.pulse.arm(time.monotonic() - 1.0)

    backend._on_timers()

    assert backend.events == ["repaint"]
    assert backend.extra_timers == 1
    assert backend._pulse.timeout(time.monotonic(), True) == pytest.approx(
        LOADING_FRAME_INTERVAL, abs=0.05
    )


def test_the_shared_frame_request_carries_levels_only_while_recording(loop) -> None:
    backend = loop().backend
    backend._reducer.levels = (255,) * SPECTRUM_BANDS

    recording = backend._frame(OverlayState.RECORDING, scale=1.0)
    transcribing = backend._frame(OverlayState.TRANSCRIBING)

    assert recording.image.size == transcribing.image.size
    assert recording.image.tobytes() != transcribing.image.tobytes()
    assert backend._visible is False


def test_closing_releases_the_display_exactly_once(loop) -> None:
    """``run`` and the helper's own ``finally`` can both close the backend."""
    backend = loop().backend

    backend.close()
    backend.close()

    assert backend.closes == 1


def test_layer_shell_refuses_without_a_wayland_session(monkeypatch) -> None:
    """The environment check comes before the connection attempt, so a machine
    with no compositor gets the exact reason instead of a library traceback.
    """
    pytest.importorskip("pywayland")
    from stenographer.overlay.platform.linux.backends.layer_shell_backend import LayerShellBackend

    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    with pytest.raises(BackendUnavailableError) as caught:
        LayerShellBackend()
    assert caught.value.reason is UnavailableReason.NO_WAYLAND_DISPLAY


def test_xwayland_refuses_without_a_display_variable(monkeypatch) -> None:
    pytest.importorskip("Xlib")
    from stenographer.overlay.platform.linux.backends.x11_overlay_backend import X11OverlayBackend

    monkeypatch.delenv("DISPLAY", raising=False)

    with pytest.raises(BackendUnavailableError) as caught:
        X11OverlayBackend()
    assert caught.value.reason is UnavailableReason.NO_X_DISPLAY


@pytest.mark.parametrize(
    ("hook", "args"),
    [
        ("_display_fd", ()),
        ("_draw", ()),
        ("_repaint", ()),
        ("_teardown", ()),
        ("_on_display_readable", (0,)),
        ("_close", ()),
    ],
)
def test_every_display_hook_is_unimplemented_until_a_backend_supplies_it(hook, args) -> None:
    """A silently inherited no-op would let a backend register itself and then
    draw nothing, which looks exactly like a working overlay that is hidden.
    """
    bare = base.HelperBackend()

    with pytest.raises(NotImplementedError):
        getattr(bare, hook)(*args)


def test_a_loading_edge_while_hidden_changes_nothing_on_screen(loop) -> None:
    """There is no surface to breathe on yet; arming the pulse without one
    would repaint a window that does not exist.
    """
    wire = loop()
    wire.send(LoadingActivityMessage(True))
    wire.end_input()

    wire.backend.run(wire.stream)

    assert wire.backend.events == []
    assert wire.backend._pulse.active is True
