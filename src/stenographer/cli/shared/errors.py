# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared command failure presentation."""

import sys


def _fatal(message: str) -> int:
    """Print a capability/config failure and return the exit-78 code."""
    print(f"stenographer: {message}", file=sys.stderr)
    return 78
