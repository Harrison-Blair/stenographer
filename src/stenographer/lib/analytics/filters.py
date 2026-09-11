# SPDX-License-Identifier: GPL-3.0-or-later
"""Validated analytics query bounds and SQL predicates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


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
