# SPDX-License-Identifier: GPL-3.0-or-later
"""Reset discards the caller's filters and works on every record."""

from __future__ import annotations

from types import SimpleNamespace

from stenographer.cli.stats.reset.handler import run
from stenographer.lib.analytics.filters import Filters

from ..conftest import checkpoint


def test_reset_ignores_the_incoming_filters_and_counts_every_source(seed, capsys):
    store = seed(
        checkpoint("hotkey-1", source="hotkey"),
        checkpoint("file-1", source="file"),
    )

    assert run(SimpleNamespace(yes=False), store, Filters(source="hotkey", outcome="empty")) == 0

    assert "Records selected for deletion: 2" in capsys.readouterr().out
    assert len(store.records(Filters(source=None))) == 2


def test_confirmed_reset_empties_the_store(seed, capsys):
    store = seed(
        checkpoint("hotkey-1", source="hotkey"),
        checkpoint("file-1", source="file"),
    )

    assert run(SimpleNamespace(yes=True), store, Filters(source="hotkey")) == 0

    assert "Deleted 2 records." in capsys.readouterr().out
    assert store.records(Filters(source=None)) == []
