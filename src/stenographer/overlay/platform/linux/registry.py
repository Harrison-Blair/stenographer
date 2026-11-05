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
from collections.abc import Callable
from functools import partial

from stenographer.lib.logging.pipeline import log_failure
from stenographer.overlay.platform.overlay_backend import OverlayBackend
from stenographer.overlay.platform.overlay_backend_spec import OverlayBackendSpec
from stenographer.overlay.protocol.backend import Backend
from stenographer.overlay.protocol.errors import BackendUnavailableError
from stenographer.overlay.protocol.unavailablereason import UnavailableReason

log = logging.getLogger(__name__)


def _load_layer_shell() -> type[OverlayBackend]:
    from stenographer.overlay.platform.linux.backends.layer_shell_backend import (
        LayerShellBackend,
    )

    return LayerShellBackend


def _load_xwayland() -> type[OverlayBackend]:
    from stenographer.overlay.platform.linux.backends.x11_overlay_backend import (
        X11OverlayBackend,
    )

    return X11OverlayBackend


def _probe(load: Callable[[], type[OverlayBackend]], backend: Backend) -> UnavailableReason | None:
    try:
        from stenographer.overlay.platform.linux.backends.base import probe_backend

        backend_class = load()
    except ImportError as exc:
        log_failure(
            log,
            logging.DEBUG,
            "overlay: backend_import_failed",
            exc,
            safe=True,
            backend=backend.value,
        )
        return UnavailableReason.BACKEND_DEPENDENCY_MISSING
    try:
        return probe_backend(backend_class)
    except Exception as exc:
        # Each backend is an independent fallback for the other.
        log_failure(
            log,
            logging.DEBUG,
            "overlay: backend_probe_failed",
            exc,
            safe=True,
            backend=backend.value,
        )
        return UnavailableReason.BACKENDS_UNAVAILABLE


def _construct(load: Callable[[], type[OverlayBackend]], backend: Backend) -> OverlayBackend:
    try:
        backend_class = load()
    except ImportError as exc:
        # The same reason the probe returns: a partial install must not read as
        # a missing compositor just because this path runs in the helper.
        log_failure(
            log,
            logging.INFO,
            "overlay_helper: backend_import_failed",
            exc,
            safe=True,
            backend=backend.value,
        )
        raise BackendUnavailableError(UnavailableReason.BACKEND_DEPENDENCY_MISSING) from None

    return backend_class()


def overlay_backends() -> tuple[OverlayBackendSpec, ...]:
    return tuple(
        OverlayBackendSpec(
            backend, partial(_probe, load, backend), partial(_construct, load, backend)
        )
        for backend, load in (
            (Backend.LAYER_SHELL, _load_layer_shell),
            (Backend.XWAYLAND, _load_xwayland),
        )
    )
