# SPDX-License-Identifier: GPL-3.0-or-later
"""Stdlib-only recognition of the private helper re-exec entry path.

This must stay importable without any runtime dependency installed: the CLI
checks it on every invocation, including dependency-free paths such as
``stenographer completion``.
"""

from __future__ import annotations

from collections.abc import Sequence

OVERLAY_ENTRY_ARG = "_overlay"


def private_entry_requested(argv: Sequence[str]) -> bool:
    """Recognize the exact non-argparse helper entry path."""
    return tuple(argv) == (OVERLAY_ENTRY_ARG,)
