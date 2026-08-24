# SPDX-License-Identifier: GPL-3.0-or-later
"""Thin per-subcommand handlers; heavy imports stay inside each handler."""

from __future__ import annotations

import argparse
import functools
from collections.abc import Callable
from typing import TYPE_CHECKING

from stenographer.cli import _fatal

if TYPE_CHECKING:
    from stenographer.config import Config


def with_config(
    handler: Callable[[argparse.Namespace, Config], int],
) -> Callable[[argparse.Namespace], int]:
    """Wrap a handler that needs configuration, reporting a key-scoped failure.

    A ``ConfigError`` never reaches the handler: its message is printed
    verbatim and the command ends at exit 78. The config import lives inside
    the wrapper so the module keeps its stdlib-only import graph.
    """

    @functools.wraps(handler)
    def wrapper(args: argparse.Namespace) -> int:
        from stenographer import config

        try:
            cfg = config.load_or_default()
        except config.ConfigError as exc:
            return _fatal(str(exc))
        return handler(args, cfg)

    return wrapper
