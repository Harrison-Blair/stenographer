# SPDX-License-Identifier: GPL-3.0-or-later
"""Overlay backend registry: layer-shell (preferred) then XWayland, in runtime order.

The backends themselves live in ``overlay_backends/`` beside this module
(helper-side); this module only knows which exist on Linux, how to probe each
read-only for ``doctor``, and how to construct each inside the helper process.
Probing is the shared construct-close-classify shape from
``overlay_backends/base.py``; a partial source environment (missing generated
bindings, PyWayland, or python-xlib) is the one failure this module classifies
itself, because it happens at import time rather than at connect time.
"""

from __future__ import annotations

from stenographer.platform.base import OverlayBackend, OverlayBackendSpec
from stenographer.status import Backend, UnavailableReason


def _probe_layer_shell() -> UnavailableReason | None:
    try:
        from stenographer.platform.linux.overlay_backends.base import probe_backend
        from stenographer.platform.linux.overlay_backends.wayland import LayerShellBackend

        return probe_backend(LayerShellBackend)
    except Exception:
        # XWayland remains a valid independent fallback.
        return UnavailableReason.BACKENDS_UNAVAILABLE


def _construct_layer_shell() -> OverlayBackend:
    from stenographer.platform.linux.overlay_backends.wayland import LayerShellBackend

    return LayerShellBackend()


def _probe_xwayland() -> UnavailableReason | None:
    try:
        from stenographer.platform.linux.overlay_backends.base import probe_backend
        from stenographer.platform.linux.overlay_backends.x11 import X11OverlayBackend

        return probe_backend(X11OverlayBackend)
    except Exception:
        return UnavailableReason.BACKENDS_UNAVAILABLE


def _construct_xwayland() -> OverlayBackend:
    from stenographer.platform.linux.overlay_backends.x11 import X11OverlayBackend

    return X11OverlayBackend()


def overlay_backends() -> tuple[OverlayBackendSpec, ...]:
    return (
        OverlayBackendSpec(Backend.LAYER_SHELL, _probe_layer_shell, _construct_layer_shell),
        OverlayBackendSpec(Backend.XWAYLAND, _probe_xwayland, _construct_xwayland),
    )
