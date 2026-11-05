# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import dataclasses

from stenographer.lib.platform.host_probe import HostProbe


@dataclasses.dataclass(frozen=True)
class Capabilities(HostProbe):
    has_mic: bool
    model_cached: bool
