# SPDX-License-Identifier: GPL-3.0-or-later
"""Deletion previews and confirmed deletion against a real store."""

from __future__ import annotations

from types import SimpleNamespace

from stenographer.cli.stats.delete.handler import run
from stenographer.lib.analytics.filters import Filters

from ..conftest import checkpoint


def test_preview_counts_the_matching_records_and_deletes_nothing(seed, capsys):
    store = seed(
        checkpoint("hotkey-1", source="hotkey"),
        checkpoint("hotkey-2", source="hotkey"),
        checkpoint("file-1", source="file"),
    )

    assert run(SimpleNamespace(yes=False), store, Filters()) == 0

    assert capsys.readouterr().out == (
        "Records selected for deletion: 2\n"
        "Run again with --yes to confirm. Queued matching checkpoints are suppressed.\n"
    )
    assert len(store.records(Filters(source=None))) == 3


def test_confirmed_deletion_removes_only_the_matching_records(seed, capsys):
    store = seed(
        checkpoint("hotkey-1", source="hotkey"),
        checkpoint("hotkey-2", source="hotkey"),
        checkpoint("file-1", source="file"),
    )

    assert run(SimpleNamespace(yes=True), store, Filters()) == 0

    assert capsys.readouterr().out == ("Records selected for deletion: 2\nDeleted 2 records.\n")
    assert [record["id"] for record in store.records(Filters(source=None))] == ["file-1"]


def test_confirmed_deletion_suppresses_a_later_queued_checkpoint(seed, capsys):
    store = seed(checkpoint("hotkey-1", source="hotkey"))

    assert run(SimpleNamespace(yes=True), store, Filters()) == 0
    capsys.readouterr()

    # The daemon's queued write for the same, already-deleted utterance.
    assert store.write_checkpoint(checkpoint("hotkey-1", source="hotkey")) is False
    assert store.records(Filters(source=None)) == []
