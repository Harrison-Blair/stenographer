# SPDX-License-Identifier: GPL-3.0-or-later
"""``stenographer devices``: list the microphones."""

from __future__ import annotations

import argparse
import sys

from stenographer.lib.audio.probe import query_devices
from stenographer.lib.platform.mic_capture import InputSources


def _format_input_devices(query: InputSources) -> list[str]:
    """Pure: one line per microphone, ``name  description``; ``*`` marks the default."""
    lines = []
    for source in query.sources:
        marker = "*" if source.name == query.default else " "
        lines.append(f"{marker} {source.name}  {source.description}")
    if not lines:
        lines.append("  (no microphones found)")
    return lines


def cmd_devices(args: argparse.Namespace) -> int:
    query = query_devices()
    if query.error is not None:
        print(f"stenographer: {query.error}", file=sys.stderr)
        return 1
    for line in _format_input_devices(query):
        print(line)
    return 0
