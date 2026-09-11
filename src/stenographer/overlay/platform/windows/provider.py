# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from collections.abc import Sequence

from stenographer.lib.platform.errors import UnsupportedPlatformError
from stenographer.overlay.platform.helper_transport import HelperTransport
from stenographer.overlay.platform.overlay_backend_spec import OverlayBackendSpec


class WindowsOverlayPlatform:
    def helper_transport(self) -> HelperTransport:
        # The overlay is disabled on Windows (``overlay_backends()`` is empty,
        # and no ``Backend`` wire value names a Windows surface yet), so the
        # supervisor has nothing to supervise. A real transport lands with the
        # overlay backend: ``CREATE_NO_WINDOW`` so the helper never flashes a
        # console, an overlapped/threaded stdout wait (``SelectSelector``
        # accepts only sockets here), and ``TerminateProcess`` escalation.
        raise UnsupportedPlatformError("the overlay helper is not available on Windows yet")

    def overlay_backends(self) -> Sequence[OverlayBackendSpec]:
        return ()

    def guidance(self):
        from .guidance import guidance

        return guidance()
