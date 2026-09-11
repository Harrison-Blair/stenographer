# SPDX-License-Identifier: GPL-3.0-or-later
"""Reset all local analytics after confirmation."""

from stenographer.cli.stats.delete.handler import run as delete
from stenographer.lib.analytics.filters import Filters


def run(args, store, filters) -> int:
    return delete(args, store, Filters(source=None))
