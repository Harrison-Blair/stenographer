# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class Capabilities:
    key_injector_ok: bool
    hotkey_access_ok: bool
    has_mic: bool
    model_cached: bool
    clipboard_ok: bool
    clipboard_backend: str
    cue_player: str | None
    service_enabled: str | None
    service_active: str | None
