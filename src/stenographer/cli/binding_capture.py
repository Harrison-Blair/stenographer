# SPDX-License-Identifier: GPL-3.0-or-later
"""Binding capture: the CLI-side platform delegator.

The pure reducer and serializer live in ``stenographer.binding_capture``; the
live capture backend lives in the active platform provider."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import TextIO


def capture_binding(
    stdin: TextIO,
    device_path: str | None,
    *,
    timeout: float = 15.0,
) -> str:
    """Capture one key/chord through the current platform's non-grabbing capture."""

    if timeout <= 0:
        raise ValueError("timeout must be positive")
    from stenographer.platform import current_platform

    return current_platform().capture_binding(stdin, device_path, timeout=timeout)
