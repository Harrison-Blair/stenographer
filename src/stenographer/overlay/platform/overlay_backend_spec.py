# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from stenographer.overlay.platform.overlay_backend import OverlayBackend
from stenographer.overlay.protocol.backend import Backend
from stenographer.overlay.protocol.unavailablereason import UnavailableReason


@dataclass(frozen=True, slots=True)
class OverlayBackendSpec:
    """One overlay backend in runtime preference order.

    ``probe`` is read-only (doctor: no surface is created) and returns a fixed
    reason or ``None`` when usable; ``construct`` builds the live backend for
    the helper and raises when unavailable.
    """

    backend: Backend
    probe: Callable[[], UnavailableReason | None]
    construct: Callable[[], OverlayBackend]
