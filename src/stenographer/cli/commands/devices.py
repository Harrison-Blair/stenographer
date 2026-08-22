# SPDX-License-Identifier: GPL-3.0-or-later
"""``stenographer devices``: list audio input devices."""

from __future__ import annotations

import argparse
import sys


def _format_input_devices(devices: list[dict], default_index: int) -> list[str]:
    """Pure: render the input-device listing, marking the default with ``*``."""
    lines = []
    for index, device in enumerate(devices):
        if device.get("max_input_channels", 0) <= 0:
            continue
        marker = "*" if index == default_index else " "
        channels = device["max_input_channels"]
        lines.append(f"{marker} {index}: {device.get('name', '?')} ({channels} ch)")
    if not lines:
        lines.append("  (no input devices found)")
    return lines


def cmd_devices(args: argparse.Namespace) -> int:
    import sounddevice

    try:
        devices = sounddevice.query_devices()
    except sounddevice.PortAudioError as exc:
        print(f"stenographer: audio subsystem unavailable: {exc}", file=sys.stderr)
        return 1
    try:
        default_index = sounddevice.default.device[0]
    except (TypeError, IndexError):
        default_index = -1
    for line in _format_input_devices(list(devices), default_index):
        print(line)
    return 0
