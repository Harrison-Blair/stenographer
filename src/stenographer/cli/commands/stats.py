# SPDX-License-Identifier: GPL-3.0-or-later
"""Thin CLI over the same reporting API used by the desktop application."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from stenographer.analytics import Filters, Store, database_path, local_date_bound


def _duration(seconds: float) -> str:
    value = int(seconds)
    hours, remainder = divmod(value, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


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
        if args.stats_command in ("delete", "reset"):
            if args.stats_command == "reset":
                filters = Filters(source=None)
            count = store.preview_delete(filters)
            print(f"Records selected for deletion: {count}")
            if not args.yes:
                print(
                    "Run again with --yes to confirm. Queued matching checkpoints are suppressed."
                )
                return 0
            print(f"Deleted {store.delete(filters)} records.")
            return 0
        if args.stats_command == "export":
            content = (
                store.export_csv(filters) if args.format == "csv" else store.export_json(filters)
            )
            if args.output:
                Path(args.output).write_text(content, encoding="utf-8")
            else:
                print(content, end="" if content.endswith("\n") else "\n")
            return 0
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
    except (ValueError, OSError, sqlite3.Error) as exc:
        # Exception messages can contain database paths. Show only the safe category.
        print(
            f"stenographer: analytics unavailable ({type(exc).__name__}). "
            "Check date filters and database access.",
            file=sys.stderr,
        )
        return 78
