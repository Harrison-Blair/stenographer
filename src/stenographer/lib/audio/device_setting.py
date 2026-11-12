# SPDX-License-Identifier: GPL-3.0-or-later
"""What the ``audio.input_device`` setting names. PURE.

Empty, ``pipewire``, ``default``, ``pulse``, and a decimal number mean the
default microphone. A number is a device index from an older version,
which no longer names a device. Any other value is a PipeWire source name.
"""

from __future__ import annotations

_DEFAULT_NAMES = frozenset({"", "pipewire", "default", "pulse"})


def capture_target(setting: str | None) -> str | None:
    """The PipeWire source name for *setting*, or ``None`` for the default source."""
    if setting is None or setting in _DEFAULT_NAMES or setting.isdecimal():
        return None
    return setting


def is_device_index(setting: str | None) -> bool:
    """True when *setting* is a device number from an older version."""
    return setting is not None and setting.isdecimal()
