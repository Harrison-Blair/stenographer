# SPDX-License-Identifier: GPL-3.0-or-later
"""``stenographer devices``: list audio input devices."""

from __future__ import annotations

import argparse
import sys

from stenographer.audio_probe import query_devices


def _default_input_index(default_device: object) -> int:
    """Pure: PortAudio's default *input* index, or ``-1`` when there is none."""
    try:
        return int(default_device[0])  # type: ignore[index]
    except (TypeError, IndexError, ValueError):
        return -1


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
    query = query_devices()
    if query.error is not None:
        print(f"stenographer: {query.error}", file=sys.stderr)
        return 1
    default_index = _default_input_index(query.default_device)
    for line in _format_input_devices(list(query.devices), default_index):
        print(line)
    return 0
