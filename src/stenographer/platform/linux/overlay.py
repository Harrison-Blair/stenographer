# SPDX-License-Identifier: GPL-3.0-or-later
"""Overlay backend registry: layer-shell (preferred) then XWayland, in runtime order.

The backends themselves stay in ``stenographer.overlay`` (helper-side); this
module only knows which exist on Linux, how to probe each read-only for
``doctor``, and how to construct each inside the helper process.
"""

from __future__ import annotations

from stenographer.platform.base import OverlayBackend, OverlayBackendSpec
from stenographer.status import Backend, UnavailableReason


def _probe_layer_shell() -> UnavailableReason | None:
    try:
        from stenographer.overlay.wayland import LayerShellBackend, WaylandUnavailableError

        try:
            backend = LayerShellBackend()
        except WaylandUnavailableError as exc:
            return exc.reason
        backend.close()
        return None
    except Exception:
        # Generated bindings or PyWayland may be unavailable in a partial
        # source environment.  XWayland remains a valid independent fallback.
        return UnavailableReason.BACKENDS_UNAVAILABLE


def _construct_layer_shell() -> OverlayBackend:
    from stenographer.overlay.wayland import LayerShellBackend

    return LayerShellBackend()


def _probe_xwayland() -> UnavailableReason | None:
    try:
        from stenographer.overlay.x11 import probe_x11

        return probe_x11()
    except Exception:
        return UnavailableReason.BACKENDS_UNAVAILABLE


def _construct_xwayland() -> OverlayBackend:
    from stenographer.overlay.x11 import X11OverlayBackend

    return X11OverlayBackend()


def overlay_backends() -> tuple[OverlayBackendSpec, ...]:
    return (
        OverlayBackendSpec(Backend.LAYER_SHELL, _probe_layer_shell, _construct_layer_shell),
        OverlayBackendSpec(Backend.XWAYLAND, _probe_xwayland, _construct_xwayland),
    )
