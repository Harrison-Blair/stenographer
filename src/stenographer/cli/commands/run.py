# SPDX-License-Identifier: GPL-3.0-or-later
"""``stenographer run``: the dictation daemon."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from stenographer.cli.commands import with_config

if TYPE_CHECKING:
    from stenographer.config import Config


@with_config
def cmd_run(args: argparse.Namespace, cfg: Config) -> int:
    from stenographer import daemon
    from stenographer.utils.logging_setup import apply_stderr_level

    # Logging was installed before any config could be read; this is the first
    # point where ``feedback.log_level`` exists.
    apply_stderr_level(cfg.feedback.log_level)
    return daemon.run(cfg)
