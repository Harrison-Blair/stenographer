# SPDX-License-Identifier: GPL-3.0-or-later
"""CLI reporting, export, and deletion of local numeric analytics."""

from __future__ import annotations

import sqlite3
import sys

from stenographer.lib.analytics.filters import Filters
from stenographer.lib.analytics.metrics import local_date_bound
from stenographer.lib.analytics.paths import database_path
from stenographer.lib.analytics.store import Store


def cmd_stats(args) -> int:
    try:
        filters = Filters(
            source=None if args.source == "all" else args.source,
            since=local_date_bound(args.since) if args.since else None,
            until=local_date_bound(args.until, end=True) if args.until else None,
            model=args.model,
            app_version=args.app_version,
            device=args.device,
            outcome=args.outcome,
        )
        if filters.since and filters.until and filters.since >= filters.until:
            raise ValueError("The start date must not be after the end date.")
        store = Store(database_path())
        if args.stats_command == "reset":
            from stenographer.cli.stats.reset.handler import run
        elif args.stats_command == "delete":
            from stenographer.cli.stats.delete.handler import run
        elif args.stats_command == "export":
            from stenographer.cli.stats.export.handler import run
        else:
            from stenographer.cli.stats.summary.handler import run
        return run(args, store, filters)
    except (ValueError, OSError, sqlite3.Error) as exc:
        # Exception messages can contain database paths. Show only the safe category.
        print(
            f"stenographer: analytics unavailable ({type(exc).__name__}). "
            "Check date filters and database access.",
            file=sys.stderr,
        )
        return 78
