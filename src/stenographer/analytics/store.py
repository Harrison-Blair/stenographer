# SPDX-License-Identifier: GPL-3.0-or-later
"""Actual SQLite persistence, revision guards, and durable deletion suppression.

A database connection belongs to one operation/thread. Readers never depend on
an active daemon. Transactions atomically update the latest cumulative record
and its checkpoint timeline. Deletion rules also suppress checkpoints whose
accepted-start write was still queued when the user deleted the date range.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stenographer.analytics.metrics import (
    OUTCOMES,
    PHASES,
    clean_context,
    clean_metrics,
    summarize,
    utc_now,
)

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Filters:
    source: str | None = "hotkey"
    since: str | None = None
    until: str | None = None
    model: str | None = None
    app_version: str | None = None
    device: str | None = None
    outcome: str | None = None

    def __post_init__(self) -> None:
        if self.source not in (None, "hotkey", "file"):
            raise ValueError("Invalid analytics source")
        for name in ("since", "until"):
            value = getattr(self, name)
            if value is not None:
                timestamp = datetime.fromisoformat(value)
                if timestamp.tzinfo is None:
                    raise ValueError("Analytics timestamp filters require an explicit timezone")
                object.__setattr__(
                    self,
                    name,
                    timestamp.astimezone(UTC).isoformat(
                        timespec="microseconds",
                    ),
                )
        if self.since and self.until and self.since >= self.until:
            raise ValueError("Analytics date range is empty or reversed")

    def matches(self, record: dict[str, Any]) -> bool:
        if self.source is not None and record["source"] != self.source:
            return False
        if self.since is not None and record["started_at"] < self.since:
            return False
        if self.until is not None and record["started_at"] >= self.until:
            return False
        if self.outcome is not None and record["outcome"] != self.outcome:
            return False
        return all(
            value is None or record["context"].get(key) == value
            for key, value in (
                ("model", self.model),
                ("app_version", self.app_version),
                ("device", self.device),
            )
        )


DEFAULT_FILTERS = Filters()


class Store:
    def __init__(self, path: Path, *, busy_timeout_ms: int = 100) -> None:
        self.path = Path(path)
        self.busy_timeout_ms = busy_timeout_ms

    @contextmanager
    def _connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=self.busy_timeout_ms / 1000)
        connection.row_factory = sqlite3.Row
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise ValueError("Unsupported analytics database schema")
            connection.execute("PRAGMA foreign_keys=ON")
            if version == 0:
                connection.executescript("""
                    CREATE TABLE IF NOT EXISTS runs (
                        run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL,
                        ended_at TEXT, context TEXT NOT NULL, health TEXT NOT NULL DEFAULT '{}',
                        process_id INTEGER, process_started REAL
                    );
                    CREATE TABLE IF NOT EXISTS utterances (
                        id TEXT PRIMARY KEY, run_id TEXT NOT NULL, source TEXT NOT NULL,
                        started_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                        revision INTEGER NOT NULL, phase TEXT NOT NULL, outcome TEXT,
                        context TEXT NOT NULL, metrics TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS utterances_started ON utterances(started_at);
                    CREATE TABLE IF NOT EXISTS checkpoints (
                        id TEXT NOT NULL REFERENCES utterances(id) ON DELETE CASCADE,
                        revision INTEGER NOT NULL, at TEXT NOT NULL, phase TEXT NOT NULL,
                        outcome TEXT, metrics TEXT NOT NULL, PRIMARY KEY(id, revision)
                    );
                    CREATE TABLE IF NOT EXISTS tombstones (id TEXT PRIMARY KEY);
                    CREATE TABLE IF NOT EXISTS deletions (
                        serial INTEGER PRIMARY KEY, deleted_at TEXT NOT NULL,
                        filters TEXT NOT NULL, affected INTEGER NOT NULL
                    );
                    PRAGMA user_version=1;
                """)
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def register_run(
        self,
        run_id: str,
        context: dict[str, Any],
        process_identity: tuple[int, float] | None = None,
    ) -> None:
        with self._connection() as db:
            db.execute(
                "INSERT OR IGNORE INTO runs(run_id,started_at,context,process_id,process_started) "
                "VALUES(?,?,?,?,?)",
                (
                    run_id,
                    utc_now(),
                    json.dumps(clean_context(context)),
                    *(process_identity or (None, None)),
                ),
            )

    def update_health(self, run_id: str, health: dict[str, Any], *, ended: bool = False) -> None:
        with self._connection() as db:
            db.execute(
                "UPDATE runs SET health=?,ended_at=COALESCE(?,ended_at) WHERE run_id=?",
                (json.dumps(health), utc_now() if ended else None, run_id),
            )

    def write_checkpoint(self, record: dict[str, Any]) -> bool:
        record = {
            **record,
            "metrics": clean_metrics(record["metrics"]),
            "context": clean_context(record["context"]),
        }
        if record["phase"] not in PHASES or record["source"] not in ("hotkey", "file"):
            raise ValueError("Invalid checkpoint vocabulary")
        if record["outcome"] is not None and record["outcome"] not in OUTCOMES:
            raise ValueError("Invalid outcome vocabulary")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM tombstones WHERE id=?", (record["id"],)).fetchone():
                return False
            for deletion in db.execute("SELECT deleted_at,filters FROM deletions"):
                if record["started_at"] <= deletion["deleted_at"] and Filters(
                    **json.loads(deletion["filters"])
                ).matches(record):
                    db.execute("INSERT OR IGNORE INTO tombstones VALUES(?)", (record["id"],))
                    # Device/outcome may only become known after deletion. Remove
                    # the earlier incomplete snapshot of this same utterance too.
                    db.execute("DELETE FROM utterances WHERE id=?", (record["id"],))
                    return False
            old = db.execute(
                "SELECT revision,phase FROM utterances WHERE id=?", (record["id"],)
            ).fetchone()
            if old and (old["revision"] >= record["revision"] or old["phase"] == "terminal"):
                return False
            if old and PHASES.index(old["phase"]) > PHASES.index(record["phase"]):
                raise ValueError("Checkpoint phase cannot regress")
            names = (
                "id",
                "run_id",
                "source",
                "started_at",
                "updated_at",
                "revision",
                "phase",
                "outcome",
                "context",
                "metrics",
            )
            values = tuple(
                json.dumps(record[key]) if key in ("context", "metrics") else record[key]
                for key in names
            )
            db.execute(
                """INSERT INTO utterances VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,
                revision=excluded.revision,phase=excluded.phase,outcome=excluded.outcome,
                context=excluded.context,metrics=excluded.metrics""",
                values,
            )
            db.execute(
                "INSERT INTO checkpoints VALUES(?,?,?,?,?,?)",
                (
                    record["id"],
                    record["revision"],
                    record["updated_at"],
                    record["phase"],
                    record["outcome"],
                    json.dumps(record["metrics"]),
                ),
            )
            return True

    def records(self, filters: Filters = DEFAULT_FILTERS) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self._connection() as db:
            records = []
            for row in db.execute("SELECT * FROM utterances ORDER BY started_at,id"):
                record = dict(row)
                for key in ("context", "metrics"):
                    record[key] = json.loads(record[key])
                if filters.matches(record):
                    records.append(record)
            return records

    def timeline(self, utterance_id: str) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self._connection() as db:
            return [
                {**dict(row), "metrics": json.loads(row["metrics"])}
                for row in db.execute(
                    "SELECT * FROM checkpoints WHERE id=? ORDER BY revision", (utterance_id,)
                )
            ]

    def report(self, filters: Filters = DEFAULT_FILTERS) -> dict[str, Any]:
        result = summarize(self.records(filters))
        result.update(schema_version=SCHEMA_VERSION, filters=asdict(filters), health=self.health())
        return result

    def health(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"runs": 0, "dropped_checkpoints": 0, "degraded": False}
        with self._connection() as db:
            rows = list(db.execute("SELECT health FROM runs"))
            health = [json.loads(row[0]) for row in rows]
            return {
                "runs": len(rows),
                "dropped_checkpoints": sum(item.get("dropped_checkpoints", 0) for item in health),
                "degraded": any(item.get("degraded", False) for item in health),
            }

    def export_json(self, filters: Filters = DEFAULT_FILTERS) -> str:
        return json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "exported_at": utc_now(),
                "units": "_s seconds; _ms milliseconds; _bytes bytes",
                "records": self.records(filters),
            },
            indent=2,
        )

    def export_csv(self, filters: Filters = DEFAULT_FILTERS) -> str:
        rows = []
        for record in self.records(filters):
            row = {key: value for key, value in record.items() if key not in ("context", "metrics")}
            row.update({f"context.{key}": value for key, value in record["context"].items()})
            row.update(record["metrics"])
            rows.append(row)
        names = sorted({key for row in rows for key in row}) or ["id", "started_at", "source"]
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()

    def preview_delete(self, filters: Filters = DEFAULT_FILTERS) -> int:
        return len(self.records(filters))

    def delete(self, filters: Filters = DEFAULT_FILTERS) -> int:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            ids = []
            for row in db.execute("SELECT * FROM utterances"):
                record = {**dict(row), "context": json.loads(row["context"])}
                if filters.matches(record):
                    ids.append((record["id"],))
            db.executemany("INSERT OR IGNORE INTO tombstones VALUES(?)", ids)
            db.executemany("DELETE FROM utterances WHERE id=?", ids)
            db.execute(
                "INSERT INTO deletions(deleted_at,filters,affected) VALUES(?,?,?)",
                (utc_now(), json.dumps(asdict(filters)), len(ids)),
            )
            return len(ids)

    def reset(self) -> int:
        return self.delete(Filters(source=None))

    def mark_interrupted(self, run_id: str, *, process_confirmed_dead: bool) -> int:
        """Only explicit process-liveness evidence may classify unfinished work."""
        if not process_confirmed_dead or not self.path.exists():
            return 0
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            timestamp = utc_now()
            db.execute(
                """INSERT INTO checkpoints(id,revision,at,phase,outcome,metrics)
                SELECT id,revision+1,?,'terminal','interrupted',metrics
                FROM utterances WHERE run_id=? AND outcome IS NULL""",
                (timestamp, run_id),
            )
            result = db.execute(
                """UPDATE utterances SET outcome='interrupted',phase='terminal',
                revision=revision+1,updated_at=? WHERE run_id=? AND outcome IS NULL""",
                (timestamp, run_id),
            )
            db.execute(
                "UPDATE runs SET ended_at=COALESCE(ended_at,?) WHERE run_id=?", (timestamp, run_id)
            )
            return result.rowcount

    def recover_interrupted(self, process_alive: Callable[[int, float], bool | None]) -> int:
        """Ask the host about registered identities; unknown liveness remains incomplete."""
        if not self.path.exists():
            return 0
        with self._connection() as db:
            runs = list(
                db.execute(
                    "SELECT run_id,process_id,process_started FROM runs "
                    "WHERE process_id IS NOT NULL AND EXISTS ("
                    "SELECT 1 FROM utterances WHERE utterances.run_id=runs.run_id "
                    "AND utterances.outcome IS NULL)"
                )
            )
        count = 0
        for run in runs:
            try:
                alive = process_alive(run["process_id"], run["process_started"])
            except Exception:
                continue
            if alive is False:
                count += self.mark_interrupted(run["run_id"], process_confirmed_dead=True)
        return count
