# SPDX-License-Identifier: GPL-3.0-or-later
"""``stenographer run``: the dictation daemon."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from stenographer.cli.shared.config import with_config

if TYPE_CHECKING:
    from stenographer.lib.config.models import Config


@with_config
def cmd_run(args: argparse.Namespace, cfg: Config) -> int:
    from stenographer.cli.run import startup as daemon

    return daemon.run(cfg)
