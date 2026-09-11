# SPDX-License-Identifier: GPL-3.0-or-later
"""Overlay backend registry: layer-shell (preferred) then XWayland, in runtime order.

The backends themselves live in ``overlay_backends/`` beside this module
(helper-side); this module only knows which exist on Linux, how to probe each
read-only for ``doctor``, and how to construct each inside the helper process.
Probing is the shared construct-close-classify shape from
``overlay_backends/base.py``; a partial source environment (missing generated
bindings, PyWayland, or python-xlib) is the one failure this module classifies
itself, because it happens at import time rather than at connect time — and it
gets its own reason, since a missing dependency and a missing compositor are
fixed by different things.

Every probe failure is logged at DEBUG and never raised: ``doctor`` renders the
returned reason for the user, and the daemon probes on a path where an absent
overlay is a supported outcome.
"""

from __future__ import annotations

import logging

from stenographer.lib.logging.pipeline import log_failure
from stenographer.overlay.platform.overlay_backend import OverlayBackend
from stenographer.overlay.platform.overlay_backend_spec import OverlayBackendSpec
from stenographer.overlay.protocol.backend import Backend
from stenographer.overlay.protocol.unavailablereason import UnavailableReason

log = logging.getLogger(__name__)


def _probe_layer_shell() -> UnavailableReason | None:
    try:
        from stenographer.overlay.platform.linux.backends.base import probe_backend
        from stenographer.overlay.platform.linux.backends.layer_shell_backend import (
            LayerShellBackend,
        )
    except ImportError as exc:
        log_failure(
            log,
            logging.DEBUG,
            "overlay: backend_import_failed",
            exc,
            safe=True,
            backend=Backend.LAYER_SHELL.value,
        )
        return UnavailableReason.BACKEND_DEPENDENCY_MISSING
    try:
        return probe_backend(LayerShellBackend)
    except Exception as exc:
        # XWayland remains a valid independent fallback.
        log_failure(
            log,
            logging.DEBUG,
            "overlay: backend_probe_failed",
            exc,
            safe=True,
            backend=Backend.LAYER_SHELL.value,
        )
        return UnavailableReason.BACKENDS_UNAVAILABLE


def _construct_layer_shell() -> OverlayBackend:
    from stenographer.overlay.platform.linux.backends.errors import BackendUnavailableError

    try:
        from stenographer.overlay.platform.linux.backends.layer_shell_backend import (
            LayerShellBackend,
        )
    except ImportError as exc:
        # The same reason the probe returns: a partial install must not read as
        # a missing compositor just because this path runs in the helper.
        log_failure(
            log,
            logging.INFO,
            "overlay_helper: backend_import_failed",
            exc,
            safe=True,
            backend=Backend.LAYER_SHELL.value,
        )
        raise BackendUnavailableError(UnavailableReason.BACKEND_DEPENDENCY_MISSING) from None

    return LayerShellBackend()


def _probe_xwayland() -> UnavailableReason | None:
    try:
        from stenographer.overlay.platform.linux.backends.base import probe_backend
        from stenographer.overlay.platform.linux.backends.x11_overlay_backend import (
            X11OverlayBackend,
        )
    except ImportError as exc:
        log_failure(
            log,
            logging.DEBUG,
            "overlay: backend_import_failed",
            exc,
            safe=True,
            backend=Backend.XWAYLAND.value,
        )
        return UnavailableReason.BACKEND_DEPENDENCY_MISSING
    try:
        return probe_backend(X11OverlayBackend)
    except Exception as exc:
        log_failure(
            log,
            logging.DEBUG,
            "overlay: backend_probe_failed",
            exc,
            safe=True,
            backend=Backend.XWAYLAND.value,
        )
        return UnavailableReason.BACKENDS_UNAVAILABLE


def _construct_xwayland() -> OverlayBackend:
    from stenographer.overlay.platform.linux.backends.errors import BackendUnavailableError

    try:
        from stenographer.overlay.platform.linux.backends.x11_overlay_backend import (
            X11OverlayBackend,
        )
    except ImportError as exc:
        log_failure(
            log,
            logging.INFO,
            "overlay_helper: backend_import_failed",
            exc,
            safe=True,
            backend=Backend.XWAYLAND.value,
        )
        raise BackendUnavailableError(UnavailableReason.BACKEND_DEPENDENCY_MISSING) from None

    return X11OverlayBackend()


def overlay_backends() -> tuple[OverlayBackendSpec, ...]:
    return (
        OverlayBackendSpec(Backend.LAYER_SHELL, _probe_layer_shell, _construct_layer_shell),
        OverlayBackendSpec(Backend.XWAYLAND, _probe_xwayland, _construct_xwayland),
    )
