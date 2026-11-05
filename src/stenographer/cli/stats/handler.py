# SPDX-License-Identifier: GPL-3.0-or-later
"""CLI reporting, export, and deletion of local numeric analytics."""

from __future__ import annotations

import sqlite3
import sys
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from stenographer.lib.analytics.filters import Filters
from stenographer.lib.analytics.store import Store, database_path
from stenographer.lib.platform import current_platform


def local_date_bound(value: str, *, end: bool = False) -> str:
    """Local calendar day to UTC; end bounds are exclusive next-day midnight."""
    day = date.fromisoformat(value)
    if end:
        day += timedelta(days=1)
    return datetime.combine(day, time.min).astimezone(UTC).isoformat(timespec="microseconds")


def cmd_stats(args) -> int:
    if args.stats_command != "export" and (args.format is not None or args.output is not None):
        print("stenographer: --format and --output require stats export", file=sys.stderr)
        return 2
    if args.stats_command == "reset" and any(
        getattr(args, name) is not None
        for name in ("source", "since", "until", "model", "app_version", "device", "outcome")
    ):
        print(
            "stenographer: stats reset deletes all records; use stats delete for filtered deletion",
            file=sys.stderr,
        )
        return 2
    try:
        filters = Filters(
            source=None if args.source == "all" else (args.source or "hotkey"),
            since=local_date_bound(args.since) if args.since else None,
            until=local_date_bound(args.until, end=True) if args.until else None,
            model=args.model,
            app_version=args.app_version,
            device=args.device,
            outcome=args.outcome,
        )
        store = Store(database_path(current_platform()))
        actions = {"reset": _reset, "delete": _delete, "export": _export, "summary": _summary}
        return actions.get(args.stats_command, _summary)(args, store, filters)
    except (ValueError, OSError, sqlite3.Error) as exc:
        # Exception messages can contain database paths. Show only the safe category.
        print(
            f"stenographer: analytics unavailable ({type(exc).__name__}). "
            "Check date filters and database access.",
            file=sys.stderr,
        )
        return 78


def _delete(args, store, filters) -> int:
    count = store.preview_delete(filters)
    print(f"Records selected for deletion: {count}")
    if not args.yes:
        print("Run again with --yes to confirm. Queued matching checkpoints are suppressed.")
        return 0
    print(f"Deleted {store.delete(filters)} records.")
    return 0


def _export(args, store, filters) -> int:
    content = store.export_csv(filters) if args.format == "csv" else store.export_json(filters)
    if args.output:
        Path(args.output).write_text(content, encoding="utf-8")
        print(f"Exported statistics to {args.output}")
    else:
        print(content, end="" if content.endswith("\n") else "\n")
    return 0


def _reset(args, store, filters) -> int:
    return _delete(args, store, Filters(source=None))


def _duration(seconds: float) -> str:
    value = int(seconds)
    hours, remainder = divmod(value, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def _summary(args, store, filters) -> int:
    report = store.report(filters)
    totals = report["totals"]
    print(f"Recognized words: {totals['recognized_words']:,}")
    print(f"Completed ASR audio: {_duration(totals['asr_audio_s'])}")
    print(f"Utterances: {totals['utterances']:,} · Active days: {totals['active_days']:,}")
    print(f"Clipboard-confirmed words: {totals['copied_words']:,}")
    print(f"Paste-chord words: {totals['chord_words']:,}")
    print(f"Incomplete utterances: {totals['incomplete']:,}")
    for name, metric in report["metrics"].items():
        if not name.endswith("_ms") or not metric["count"]:
            continue
        print(
            f"{name}: average {metric['average']:.1f}, p95 {metric['p95']:.1f}, "
            f"p99 {metric['p99']:.1f} ms (n={metric['count']}, missing={metric['missing']})"
        )
    health = report["health"]
    print(
        f"Collection: {'degraded' if health['degraded'] else 'available'}; "
        f"dropped checkpoints: {health['dropped_checkpoints']}"
    )
    return 0
