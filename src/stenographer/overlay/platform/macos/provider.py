# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from collections.abc import Sequence

from stenographer.lib.platform.errors import UnsupportedPlatformError
from stenographer.overlay.platform.helper_transport import HelperTransport
from stenographer.overlay.platform.overlay_backend_spec import OverlayBackendSpec


class MacOSOverlayPlatform:
    def helper_transport(self) -> HelperTransport:
        raise UnsupportedPlatformError("the overlay helper is not available on macOS yet")

    def overlay_backends(self) -> Sequence[OverlayBackendSpec]:
        return ()

    def guidance(self):
        from .guidance import guidance

        return guidance()
