# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure tests for what the helper tells the parent when no backend will start.

The helper is the only process that knows *why* a backend refused; the reason
it forwards is the whole diagnostic the parent and ``doctor`` ever see.
"""

from __future__ import annotations

from stenographer.overlay.supervisor import selected_unavailable_reason
from stenographer.status import (
    UnavailableMessage,
    UnavailableReason,
    decode_message,
    encode_message,
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
