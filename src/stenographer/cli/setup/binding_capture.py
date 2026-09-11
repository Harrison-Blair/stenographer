# SPDX-License-Identifier: GPL-3.0-or-later
"""Binding capture: the CLI-side platform delegator.

The pure reducer and serializer live in ``stenographer.lib.hotkey.capture``; the
live capture backend lives in the active platform provider."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import TextIO

    from stenographer.lib.platform.platform import Platform


def capture_binding(
    stdin: TextIO,
    device_path: str | None,
    *,
    timeout: float = 15.0,
    platform: Platform | None = None,
) -> str:
    """Capture one key/chord through a platform's non-grabbing capture.

    *platform* defaults to the active provider, so callers keep delegating to
    the current platform while tests can pass a substitute provider.
    """

    if timeout <= 0:
        raise ValueError("timeout must be positive")
    from stenographer.lib.platform import current_platform

    plat = platform if platform is not None else current_platform()
    return plat.capture_binding(stdin, device_path, timeout=timeout)
