# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from collections.abc import Sequence

from stenographer.overlay.platform.helper_transport import HelperTransport
from stenographer.overlay.platform.overlay_backend_spec import OverlayBackendSpec


class LinuxOverlayPlatform:
    def helper_transport(self) -> HelperTransport:
        from stenographer.overlay.platform.linux.linux_helper_transport import LinuxHelperTransport

        return LinuxHelperTransport()

    def overlay_backends(self) -> Sequence[OverlayBackendSpec]:
        from stenographer.overlay.platform.linux.registry import overlay_backends

        return overlay_backends()

    def guidance(self):
        from .guidance import guidance

        return guidance()
