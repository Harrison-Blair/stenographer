# SPDX-License-Identifier: GPL-3.0-or-later
"""Thin per-subcommand handlers; heavy imports stay inside each handler."""

from __future__ import annotations

import argparse
import functools
from collections.abc import Callable
from typing import TYPE_CHECKING

from stenographer.cli.shared.errors import _fatal

if TYPE_CHECKING:
    from stenographer.lib.config.models import Config


def with_config(
    handler: Callable[[argparse.Namespace, Config], int],
) -> Callable[[argparse.Namespace], int]:
    """Wrap a handler that needs configuration, reporting a key-scoped failure.

    A ``ConfigError`` never reaches the handler: its message is printed
    verbatim and the command ends at exit 78. The config import lives inside
    the wrapper so the module keeps its stdlib-only import graph. This is also
    the first point in any config-reading command where ``feedback.log_level``
    exists, so the stderr threshold is applied here rather than per handler.
    """

    @functools.wraps(handler)
    def wrapper(args: argparse.Namespace) -> int:
        from stenographer.lib.config.errors import ConfigError
        from stenographer.lib.config.paths import load_or_default
        from stenographer.lib.logging.pipeline import apply_stderr_level

        try:
            cfg = load_or_default()
        except ConfigError as exc:
            return _fatal(str(exc))
        apply_stderr_level(cfg.feedback.log_level)
        return handler(args, cfg)

    return wrapper
