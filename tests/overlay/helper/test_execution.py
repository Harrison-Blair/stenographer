# SPDX-License-Identifier: GPL-3.0-or-later
"""What the helper process writes on its real stdout pipe before it exits.

``run_overlay_helper`` is the whole child: it picks a backend, announces the
outcome in exactly one record, and serves the parent's stream. Every test here
drives it over a real ``os.pipe`` and reads the bytes the parent would have
read, because the record on the wire — not an internal call — is the contract.

The platform is the one injected collaborator: ``current_platform`` is the
module-level seam the helper uses to reach its host, so a small fake platform
stands in for one with a display server.
"""

from __future__ import annotations

import io
import logging
import os

import pytest

from stenographer.lib.platform.errors import UnsupportedPlatformError
from stenographer.overlay.helper.errors import _NoBackendError
from stenographer.overlay.helper.execution import _select_backend, run_overlay_helper
from stenographer.overlay.platform.overlay_backend_spec import OverlayBackendSpec
from stenographer.overlay.protocol.backend import Backend
from stenographer.overlay.protocol.codec import decode_message, encode_message
from stenographer.overlay.protocol.errors import ProtocolError
from stenographer.overlay.protocol.messages import ReadyMessage, UnavailableMessage
from stenographer.overlay.protocol.unavailablereason import UnavailableReason

_EXECUTION = "stenographer.overlay.helper.execution.current_platform"

_LOG = "stenographer.overlay.supervision.constants"


class _Platform:
    """The three methods an ``OverlayPlatform`` offers; only one is used here."""

    def __init__(self, specs) -> None:
        self._specs = specs

    def overlay_backends(self):
        return self._specs

    def helper_transport(self):  # pragma: no cover - the child never spawns
        raise AssertionError("the helper never spawns another helper")

    def guidance(self):  # pragma: no cover - guidance is a parent-side concern
        raise AssertionError("the helper never renders guidance")


class _Backend:
    """A backend that records what it was served and how it was released."""

    def __init__(
        self,
        backend: Backend = Backend.XWAYLAND,
        *,
        run_error: BaseException | None = None,
        close_error: BaseException | None = None,
    ) -> None:
        self.backend = backend
        self._run_error = run_error
        self._close_error = close_error
        self.served: list[object] = []
        self.closes = 0

    def run(self, input_stream) -> None:
        self.served.append(input_stream)
        if self._run_error is not None:
            raise self._run_error

    def close(self) -> None:
        self.closes += 1
        if self._close_error is not None:
            raise self._close_error


def _refusing(backend: Backend, error: BaseException):
    def construct():
        raise error

    return OverlayBackendSpec(backend, lambda: None, construct)


def _offering(backend_object: _Backend):
    return OverlayBackendSpec(backend_object.backend, lambda: None, lambda: backend_object)


@pytest.fixture
def helper_logging(tmp_path, monkeypatch):
    """Send the helper's own log file to *tmp_path* and undo its logger surgery.

    ``run_overlay_helper`` calls ``setup_helper_logging``, which installs a file
    handler on the shared ``stenographer`` logger and stops it propagating. Both
    have to be restored or every later test in the session loses its records.
    """
    logger = logging.getLogger("stenographer")
    original = list(logger.handlers)
    level, propagate = logger.level, logger.propagate
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    yield tmp_path / "state"
    for handler in list(logger.handlers):
        if handler not in original:
            logger.removeHandler(handler)
            handler.close()
    logger.handlers[:] = original
    logger.setLevel(level)
    logger.propagate = propagate


@pytest.fixture
def wire():
    """A real pipe standing in for the helper's stdout, plus its reader."""
    read_fd, write_fd = os.pipe()
    writer = os.fdopen(write_fd, "wb", buffering=0)
    try:
        yield writer, read_fd
    finally:
        writer.close()
        os.close(read_fd)


def _written(writer, read_fd) -> list[object]:
    """Decode every record the helper actually put on the pipe."""
    writer.flush()
    os.set_blocking(read_fd, False)
    try:
        payload = os.read(read_fd, 4096)
    except BlockingIOError:
        payload = b""
    return [decode_message(line + b"\n") for line in payload.split(b"\n") if line]


@pytest.fixture
def propagating(monkeypatch):
    """Keep ``stenographer`` records reaching caplog's root handler."""
    monkeypatch.setattr(logging.getLogger("stenographer"), "propagate", True)


def test_no_backend_error_carries_the_reason_as_its_whole_text() -> None:
    error = _NoBackendError(UnavailableReason.X_ARGB_UNAVAILABLE)

    assert error.reason is UnavailableReason.X_ARGB_UNAVAILABLE
    assert str(error) == "x_argb_unavailable"


def test_selection_takes_the_first_usable_backend_and_logs_the_rest(
    monkeypatch, caplog, propagating
) -> None:
    """Preference order is the registry's order, and a refusal is never silent.

    The rejected backend's fixed reason has to reach the log even though the
    parent is told nothing about it: the helper is the only process that saw it.
    """
    usable = _Backend(Backend.XWAYLAND)
    refused = RuntimeError("no compositor")
    refused.reason = UnavailableReason.REQUIRED_GLOBALS_MISSING
    monkeypatch.setattr(
        _EXECUTION,
        lambda: _Platform((_refusing(Backend.LAYER_SHELL, refused), _offering(usable))),
    )

    with caplog.at_level(logging.INFO, logger=_LOG):
        assert _select_backend() is usable

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "backend_rejected" in message
        and "backend=layer-shell" in message
        and "reason=required_wayland_globals_missing" in message
        for message in messages
    ), messages
    assert any("backend_selected backend=xwayland" in message for message in messages)


def test_a_bare_import_error_is_reported_as_a_missing_dependency(monkeypatch) -> None:
    """A backend module that dies before it can classify itself is still a
    partial install, which is fixed by reinstalling rather than by starting a
    session — so it must not fold to the generic ``backends_unavailable``.
    """
    monkeypatch.setattr(
        _EXECUTION,
        lambda: _Platform((_refusing(Backend.LAYER_SHELL, ImportError("no pywayland")),)),
    )

    with pytest.raises(_NoBackendError) as caught:
        _select_backend()
    assert caught.value.reason is UnavailableReason.BACKEND_DEPENDENCY_MISSING


def test_an_unreported_refusal_keeps_the_unspecific_reason(monkeypatch) -> None:
    monkeypatch.setattr(
        _EXECUTION,
        lambda: _Platform((_refusing(Backend.XWAYLAND, RuntimeError("boom")),)),
    )

    with pytest.raises(_NoBackendError) as caught:
        _select_backend()
    assert caught.value.reason is UnavailableReason.BACKENDS_UNAVAILABLE


def test_every_backend_refusing_is_a_clean_exit_with_one_record(
    monkeypatch, helper_logging, wire
) -> None:
    """An unavailable overlay is not a helper failure: the exit status is 0.

    The parent blocks on its readiness deadline, so the single record is the
    whole difference between a three-second stall and an immediate diagnosis.
    """
    writer, read_fd = wire
    wayland = RuntimeError("no wayland")
    wayland.reason = UnavailableReason.NO_WAYLAND_DISPLAY
    x11 = RuntimeError("no X")
    x11.reason = UnavailableReason.X_ARGB_UNAVAILABLE
    monkeypatch.setattr(
        _EXECUTION,
        lambda: _Platform(
            (
                _refusing(Backend.LAYER_SHELL, wayland),
                _refusing(Backend.XWAYLAND, x11),
            )
        ),
    )

    assert run_overlay_helper(io.BytesIO(b""), writer) == 0
    assert _written(writer, read_fd) == [UnavailableMessage(UnavailableReason.X_ARGB_UNAVAILABLE)]


def test_a_host_that_cannot_offer_backends_at_all_fails_loudly(
    monkeypatch, helper_logging, wire
) -> None:
    """No platform support is the helper's own failure, so the status is 1 —
    and the reason is the unspecific one, because no backend supplied a fixed
    one to forward.
    """
    writer, read_fd = wire

    def unsupported():
        raise UnsupportedPlatformError("no overlay host")

    monkeypatch.setattr(_EXECUTION, unsupported)

    assert run_overlay_helper(io.BytesIO(b""), writer) == 1
    assert _written(writer, read_fd) == [UnavailableMessage(UnavailableReason.BACKENDS_UNAVAILABLE)]


def test_a_served_backend_announces_readiness_and_is_always_closed(
    monkeypatch, helper_logging, wire
) -> None:
    writer, read_fd = wire
    backend = _Backend(Backend.LAYER_SHELL)
    monkeypatch.setattr(_EXECUTION, lambda: _Platform((_offering(backend),)))
    stream = io.BytesIO(encode_message(ReadyMessage(Backend.LAYER_SHELL)).encode("ascii"))

    assert run_overlay_helper(stream, writer) == 0

    assert _written(writer, read_fd) == [ReadyMessage(Backend.LAYER_SHELL)]
    assert backend.served == [stream]
    assert backend.closes == 1


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (ProtocolError("malformed record"), UnavailableReason.PROTOCOL_ERROR),
        (RuntimeError("display vanished"), UnavailableReason.BACKEND_LOST),
    ],
)
def test_a_backend_that_dies_mid_session_reports_why_after_readiness(
    monkeypatch, helper_logging, wire, error, reason
) -> None:
    """Two records, in order: the parent already saw ``ready``, so the second
    one is what turns a silent disappearance into ``backend_lost``.
    """
    writer, read_fd = wire
    backend = _Backend(Backend.XWAYLAND, run_error=error)
    monkeypatch.setattr(_EXECUTION, lambda: _Platform((_offering(backend),)))

    assert run_overlay_helper(io.BytesIO(b""), writer) == 1

    assert _written(writer, read_fd) == [
        ReadyMessage(Backend.XWAYLAND),
        UnavailableMessage(reason),
    ]
    assert backend.closes == 1


def test_a_backend_that_fails_to_close_never_changes_the_exit_status(
    monkeypatch, helper_logging, wire
) -> None:
    """Release is best effort: a display already gone cannot be released, and
    turning that into a nonzero exit would spend the parent's restart budget on
    a helper that did its whole job.
    """
    writer, read_fd = wire
    backend = _Backend(Backend.XWAYLAND, close_error=OSError("display gone"))
    monkeypatch.setattr(_EXECUTION, lambda: _Platform((_offering(backend),)))

    assert run_overlay_helper(io.BytesIO(b""), writer) == 0

    assert backend.closes == 1
    assert _written(writer, read_fd) == [ReadyMessage(Backend.XWAYLAND)]
