# SPDX-License-Identifier: GPL-3.0-or-later
from collections.abc import Sequence
from typing import Protocol

from stenographer.overlay.platform.guidance import OverlayGuidance
from stenographer.overlay.platform.helper_transport import HelperTransport
from stenographer.overlay.platform.overlay_backend_spec import OverlayBackendSpec


class OverlayPlatform(Protocol):
    def helper_transport(self) -> HelperTransport: ...
    def overlay_backends(self) -> Sequence[OverlayBackendSpec]: ...
    def guidance(self) -> OverlayGuidance: ...
