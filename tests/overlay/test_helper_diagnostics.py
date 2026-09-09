# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure tests for what the helper tells the parent when no backend will start.

The helper is the only process that knows *why* a backend refused; the reason
it forwards is the whole diagnostic the parent and ``doctor`` ever see. The
fold that picks it lives in ``status`` because two callers must agree on it —
the helper's construct loop and the read-only probe behind ``doctor``.
"""

from __future__ import annotations

from stenographer.capabilities import OverlayCapability, probe_overlay
from stenographer.platform.base import OverlayBackendSpec
from stenographer.status import (
    Backend,
    UnavailableMessage,
    UnavailableReason,
    decode_message,
    encode_message,
    selected_unavailable_reason,
)


def test_the_last_specific_refusal_is_what_the_parent_is_told():
    """Backends are tried in preference order, so the last one is the fallback.

    Seen to FAIL against the pre-propagation helper, whose ``_select_backend``
    swallowed every ``BackendUnavailableError.reason`` and raised a bare
    ``RuntimeError`` — the parent only ever received ``BACKENDS_UNAVAILABLE``.
    """

    reasons = [UnavailableReason.NO_WAYLAND_DISPLAY, UnavailableReason.X_ARGB_UNAVAILABLE]
    assert selected_unavailable_reason(reasons) is UnavailableReason.X_ARGB_UNAVAILABLE


def test_an_unreported_last_refusal_falls_back_to_the_specific_earlier_one():
    reasons = [UnavailableReason.REQUIRED_GLOBALS_MISSING, None]
    assert selected_unavailable_reason(reasons) is UnavailableReason.REQUIRED_GLOBALS_MISSING


def test_the_unknown_case_keeps_the_unspecific_reason():
    assert selected_unavailable_reason([]) is UnavailableReason.BACKENDS_UNAVAILABLE
    assert selected_unavailable_reason([None, None]) is UnavailableReason.BACKENDS_UNAVAILABLE
    assert (
        selected_unavailable_reason([UnavailableReason.BACKENDS_UNAVAILABLE])
        is UnavailableReason.BACKENDS_UNAVAILABLE
    )


def test_the_dependency_reason_round_trips_over_the_v4_protocol():
    """The reason set is fixed data, so a new value needs no protocol bump.

    Seen to FAIL before ``BACKEND_DEPENDENCY_MISSING`` existed
    (``AttributeError`` on the enum member).
    """

    message = UnavailableMessage(UnavailableReason.BACKEND_DEPENDENCY_MISSING)
    record = encode_message(message)

    assert '"v":4' in record
    assert '"reason":"backend_dependency_missing"' in record
    assert decode_message(record) == message


def test_doctor_and_the_helper_fold_the_same_refusals_the_same_way(monkeypatch):
    """A generic last refusal must not hide a specific earlier one from doctor.

    Seen to FAIL against ``probe_overlay``'s own ``reason or
    BACKENDS_UNAVAILABLE``, which kept the *last* reason: layer-shell's
    ``required_wayland_globals_missing`` was reported by the helper's log and
    swallowed by the report, which said ``backends_unavailable``.
    """

    refusals = {
        Backend.LAYER_SHELL: UnavailableReason.REQUIRED_GLOBALS_MISSING,
        Backend.XWAYLAND: UnavailableReason.BACKENDS_UNAVAILABLE,
    }
    specs = tuple(
        OverlayBackendSpec(backend, (lambda r=reason: r), _unreachable)
        for backend, reason in refusals.items()
    )
    monkeypatch.setattr(
        "stenographer.capabilities.current_platform", lambda: _Platform(specs), raising=True
    )

    assert probe_overlay(True) == OverlayCapability.unavailable(
        UnavailableReason.REQUIRED_GLOBALS_MISSING
    )


def _unreachable():
    raise AssertionError("probe_overlay must never construct a backend")


class _Platform:
    """The one method ``probe_overlay`` calls; no host is involved."""

    def __init__(self, specs):
        self._specs = specs

    def overlay_backends(self):
        return self._specs
