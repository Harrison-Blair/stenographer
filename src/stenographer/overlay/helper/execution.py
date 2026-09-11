# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import contextlib
import logging
import sys
from typing import BinaryIO

from stenographer.lib.logging.pipeline import fmt_event, log_failure
from stenographer.overlay.helper.errors import _NoBackendError
from stenographer.overlay.logging.pipeline import setup_helper_logging
from stenographer.overlay.platform import current_platform
from stenographer.overlay.protocol.codec import encode_message
from stenographer.overlay.protocol.errors import ProtocolError
from stenographer.overlay.protocol.messages import (
    ReadyMessage,
    UnavailableMessage,
)
from stenographer.overlay.protocol.ordering import (
    selected_unavailable_reason,
)
from stenographer.overlay.protocol.unavailablereason import UnavailableReason
from stenographer.overlay.supervision.constants import log


def _write_helper_message(stream: BinaryIO, message: ReadyMessage | UnavailableMessage) -> None:
    stream.write(encode_message(message).encode("ascii"))
    stream.flush()


def _reported_reason(exc: BaseException) -> UnavailableReason | None:
    """The fixed reason a backend attached to its refusal, if it attached one.

    Read by attribute rather than by exception class: ``BackendUnavailableError``
    lives with the backends inside the platform package, and this module is core.
    """
    reason = getattr(exc, "reason", None)
    return reason if isinstance(reason, UnavailableReason) else None


def _select_backend():
    """Construct the first available platform backend; imports stay helper-local."""
    reasons: list[UnavailableReason | None] = []
    for spec in current_platform().overlay_backends():
        try:
            backend = spec.construct()
        except Exception as exc:
            reason = _reported_reason(exc)
            if reason is None and isinstance(exc, ImportError):
                # A backend module that fails to import before it can raise its
                # own classified error is still a missing dependency.
                reason = UnavailableReason.BACKEND_DEPENDENCY_MISSING
            reasons.append(reason)
            log_failure(
                log,
                logging.INFO,
                "overlay_helper: backend_rejected",
                exc,
                safe=True,
                backend=spec.backend.value,
                reason=reason.value if reason is not None else "unreported",
            )
            continue
        log.info(fmt_event("overlay_helper", "backend_selected", backend=spec.backend.value))
        return backend
    raise _NoBackendError(selected_unavailable_reason(reasons))


def run_overlay_helper(
    input_stream: BinaryIO | None = None,
    output_stream: BinaryIO | None = None,
) -> int:
    """Run the private display helper protocol endpoint.

    In the child only the module logger is used, but its records land in the
    helper's own ``overlay-helper.log``: ``setup_helper_logging`` is what
    reconfigures the shared ``stenographer`` logger this one propagates to.

    Every exit writes exactly one reply. The parent blocks on the readiness
    deadline, so a helper that dies without a record costs it three seconds and
    tells it nothing about why.
    """
    input_stream = input_stream if input_stream is not None else sys.stdin.buffer
    output_stream = output_stream if output_stream is not None else sys.stdout.buffer
    setup_helper_logging()
    try:
        backend = _select_backend()
    except _NoBackendError as exc:
        log.info(fmt_event("overlay_helper", "unavailable", reason=exc.reason.value))
        _write_helper_message(output_stream, UnavailableMessage(exc.reason))
        return 0
    except Exception as exc:
        # The host itself refused (no platform support, no backend registry):
        # not a backend's fixed reason, so the unspecific one is the honest one.
        log_failure(log, logging.WARNING, "overlay_helper: selection_failed", exc, safe=True)
        with contextlib.suppress(Exception):
            _write_helper_message(
                output_stream, UnavailableMessage(UnavailableReason.BACKENDS_UNAVAILABLE)
            )
        return 1

    try:
        _write_helper_message(output_stream, ReadyMessage(backend.backend))
        log.info(fmt_event("overlay_helper", "ready", backend=backend.backend.value))
        backend.run(input_stream)
    except ProtocolError as exc:
        log_failure(log, logging.WARNING, "overlay_helper: protocol_error", exc, safe=True)
        with contextlib.suppress(Exception):
            _write_helper_message(
                output_stream, UnavailableMessage(UnavailableReason.PROTOCOL_ERROR)
            )
        return 1
    except Exception as exc:
        log_failure(log, logging.WARNING, "overlay_helper: backend_lost", exc, safe=True)
        with contextlib.suppress(Exception):
            _write_helper_message(output_stream, UnavailableMessage(UnavailableReason.BACKEND_LOST))
        return 1
    finally:
        try:
            backend.close()
        except Exception as exc:
            log_failure(log, logging.DEBUG, "overlay_helper: close_failed", exc, safe=True)
        log.info(fmt_event("overlay_helper", "closed"))
    return 0
