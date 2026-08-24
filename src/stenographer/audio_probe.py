# SPDX-License-Identifier: GPL-3.0-or-later
"""One PortAudio input-device enumeration for the whole program.

The capability gate, `setup`, and `devices` all ask the same question — which
PortAudio devices can record — so :func:`query_devices` is the only place
that imports
``sounddevice`` (lazily, so the parser stays cheap). It has a single failure
policy: the enumeration is advisory at every call site, so ANY failure — an
absent ``sounddevice`` (``ImportError``), a missing PortAudio library
(``OSError``), or anything the query itself raises — degrades to an empty
result carrying a human-readable ``error``. It never raises: a crashed
suggestion probe would take down the setup wizard mid-prompt.

Callers keep their own shape through the pure adapters below — a bool for the
doctor gate, ``(value, label)`` pairs for the setup menu, rendered lines for
``stenographer devices`` — and decide for themselves whether ``error`` is worth
reporting or is simply "no suggestions".
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence


@dataclasses.dataclass(frozen=True, slots=True)
class DeviceQuery:
    """Raw PortAudio data: every device, the default input/output pair, or why not."""

    devices: tuple[dict, ...] = ()
    default_device: tuple[int, ...] | None = None
    error: str | None = None


def query_devices() -> DeviceQuery:
    """Enumerate PortAudio devices under the module's one failure policy."""
    try:
        import sounddevice
    except (ImportError, OSError) as exc:
        return DeviceQuery(error=f"audio support unavailable: {exc}")

    try:
        devices = tuple(sounddevice.query_devices())
        default_device = tuple(sounddevice.default.device)
    except sounddevice.PortAudioError as exc:
        return DeviceQuery(error=f"audio subsystem unavailable: {exc}")
    except Exception as exc:
        return DeviceQuery(error=f"audio support unavailable: {exc}")
    return DeviceQuery(devices=devices, default_device=default_device)


def has_input_device(devices: Sequence[dict]) -> bool:
    """Pure: whether any enumerated device can record."""
    return any(device.get("max_input_channels", 0) > 0 for device in devices)


def input_device_choices(devices: Sequence[dict]) -> list[tuple[str, str]]:
    """Pure: selectable input devices as ``(value, label)`` pairs, PortAudio index first."""
    return [
        (str(index), f"{index}: {device.get('name', '?')}")
        for index, device in enumerate(devices)
        if device.get("max_input_channels", 0) > 0
    ]
