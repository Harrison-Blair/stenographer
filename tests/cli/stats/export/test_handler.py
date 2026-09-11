# SPDX-License-Identifier: GPL-3.0-or-later
"""JSON and CSV export to standard output or a real file."""

from __future__ import annotations

import csv
import io
import json
from types import SimpleNamespace

from stenographer.cli.stats.export.handler import run
from stenographer.lib.analytics.filters import Filters

from ..conftest import checkpoint


def test_json_export_to_stdout_carries_the_matching_records(seed, capsys):
    store = seed(
        checkpoint("hotkey-1", source="hotkey", recognized_words=5),
        checkpoint("file-1", source="file", recognized_words=7),
    )

    assert run(SimpleNamespace(format="json", output=None), store, Filters()) == 0

    out = capsys.readouterr().out
    assert out.endswith("\n")
    payload = json.loads(out)
    assert [record["id"] for record in payload["records"]] == ["hotkey-1"]
    assert payload["records"][0]["metrics"]["recognized_words"] == 5


def test_csv_export_to_stdout_is_a_single_trailing_newline_document(seed, capsys):
    store = seed(checkpoint("hotkey-1", source="hotkey", recognized_words=5))

    assert run(SimpleNamespace(format="csv", output=None), store, Filters()) == 0

    out = capsys.readouterr().out
    # export_csv already ends in a newline; print must not add a second one.
    assert not out.endswith("\n\n")
    rows = list(csv.DictReader(io.StringIO(out)))
    assert len(rows) == 1
    assert rows[0]["id"] == "hotkey-1"
    assert rows[0]["recognized_words"] == "5"
    assert rows[0]["context.model"] == "medium.en"


def test_export_to_a_file_writes_there_and_prints_nothing(seed, tmp_path, capsys):
    store = seed(checkpoint("hotkey-1", source="hotkey", recognized_words=5))
    target = tmp_path / "export" / "analytics.json"
    target.parent.mkdir()

    assert run(SimpleNamespace(format="json", output=str(target)), store, Filters()) == 0

    assert capsys.readouterr().out == ""
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert [record["id"] for record in payload["records"]] == ["hotkey-1"]
