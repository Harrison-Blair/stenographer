# SPDX-License-Identifier: GPL-3.0-or-later
"""Advisory audio-device enumeration results."""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True, slots=True)
class DeviceQuery:
    """Raw PortAudio data: every device, the default input/output pair, or why not."""

    devices: tuple[dict, ...] = ()
    default_device: tuple[int, ...] | None = None
    error: str | None = None
