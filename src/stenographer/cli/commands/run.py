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

    return daemon.run(cfg)
