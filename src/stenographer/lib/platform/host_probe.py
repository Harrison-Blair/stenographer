# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HostProbe:
    """The platform-owned half of ``capabilities.Capabilities`` (read-only, no writes).

    Field names are shared verbatim with the core dataclass and its
    ``REQUIRED`` gate — no per-OS renaming anywhere in the chain.
    """

    key_injector_ok: bool
    hotkey_access_ok: bool
    clipboard_ok: bool
    clipboard_backend: str
    cue_player: str | None
    service_enabled: str | None
    service_active: str | None
