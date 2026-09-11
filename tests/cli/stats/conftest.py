# SPDX-License-Identifier: GPL-3.0-or-later
"""Real argument namespaces and real temporary SQLite stores for the stats command.

``XDG_STATE_HOME`` is the one knob every host provider honours, so redirecting
it points :func:`database_path` at a temporary directory without patching the
platform layer: the command opens the same file the fixture seeded.
"""

from __future__ import annotations

import pathlib
from typing import Any

import pytest

from stenographer.cli.parser import build_parser
from stenographer.lib.analytics.store import Store

#: A fixed instant well inside any local calendar day, so a report's local-day
#: bucketing is stable wherever the suite runs.
STARTED_AT = "2026-03-05T12:00:00.000000+00:00"


def checkpoint(
    identity: str = "utt-1",
    *,
    source: str = "hotkey",
    started_at: str = STARTED_AT,
    phase: str = "terminal",
    outcome: str | None = "success",
    context: dict[str, Any] | None = None,
    **metrics: Any,
) -> dict[str, Any]:
    """One terminal analytics checkpoint in the store's own vocabulary."""

    return {
        "id": identity,
        "run_id": "run",
        "source": source,
        "started_at": started_at,
        "updated_at": started_at,
        "revision": 0,
        "phase": phase,
        "outcome": outcome,
        "context": {"model": "medium.en", "device": "USB mic", "app_version": "1.2.3"}
        if context is None
        else context,
        "metrics": metrics,
    }


@pytest.fixture
def stats_args():
    """Parse a real ``stenographer stats ...`` command line into a namespace."""

    def build(*argv: str):
        return build_parser().parse_args(["stats", *argv])

    return build


@pytest.fixture
def analytics_home(tmp_path, monkeypatch) -> pathlib.Path:
    """Redirect the host state directory and return the analytics database path."""

    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    return state / "stenographer" / "analytics.sqlite3"


@pytest.fixture
def seed(analytics_home):
    """Write real checkpoints into the database the command will open."""

    def write(*records: dict[str, Any]) -> Store:
        store = Store(analytics_home)
        for record in records:
            store.write_checkpoint(record)
        return store

    return write
