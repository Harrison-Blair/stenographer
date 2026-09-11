# SPDX-License-Identifier: GPL-3.0-or-later
"""Filter construction, subcommand dispatch, and the safe failure report of ``stats``.

Every case runs the real command against a real temporary SQLite database, so
what is asserted is what a user would see.
"""

from __future__ import annotations

import json

from stenographer.cli.stats.handler import cmd_stats
from stenographer.lib.analytics.metrics import local_date_bound

from .conftest import checkpoint


def test_source_filter_defaults_to_hotkey_and_all_selects_every_source(
    stats_args,
    seed,
    capsys,
):
    seed(
        checkpoint("hotkey-1", source="hotkey", recognized_words=5),
        checkpoint("file-1", source="file", recognized_words=7),
    )

    assert cmd_stats(stats_args()) == 0
    assert "Recognized words: 5" in capsys.readouterr().out

    assert cmd_stats(stats_args("--source", "all")) == 0
    assert "Recognized words: 12" in capsys.readouterr().out

    assert cmd_stats(stats_args("--source", "file")) == 0
    assert "Recognized words: 7" in capsys.readouterr().out


def test_context_and_outcome_filters_reach_the_store(stats_args, seed, capsys):
    seed(
        checkpoint(
            "kept",
            context={"model": "medium.en", "device": "USB mic", "app_version": "1.2.3"},
            outcome="success",
            recognized_words=4,
        ),
        checkpoint(
            "other-model",
            context={"model": "small.en", "device": "USB mic", "app_version": "1.2.3"},
            outcome="success",
            recognized_words=40,
        ),
        checkpoint(
            "other-device",
            context={"model": "medium.en", "device": "Laptop mic", "app_version": "1.2.3"},
            outcome="success",
            recognized_words=400,
        ),
        checkpoint(
            "other-version",
            context={"model": "medium.en", "device": "USB mic", "app_version": "9.9.9"},
            outcome="success",
            recognized_words=4000,
        ),
        checkpoint(
            "other-outcome",
            context={"model": "medium.en", "device": "USB mic", "app_version": "1.2.3"},
            outcome="empty",
            recognized_words=40000,
        ),
    )

    code = cmd_stats(
        stats_args(
            "--model",
            "medium.en",
            "--device",
            "USB mic",
            "--app-version",
            "1.2.3",
            "--outcome",
            "success",
        )
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "Recognized words: 4" in out
    assert "Utterances: 1" in out


def test_day_bounds_are_inclusive_of_both_named_local_days(stats_args, seed, capsys):
    seed(
        checkpoint("before", started_at=local_date_bound("2026-03-04"), recognized_words=1),
        checkpoint("first", started_at=local_date_bound("2026-03-05"), recognized_words=2),
        checkpoint("last", started_at=local_date_bound("2026-03-06"), recognized_words=4),
        checkpoint("after", started_at=local_date_bound("2026-03-07"), recognized_words=8),
    )

    assert cmd_stats(stats_args("--since", "2026-03-05", "--until", "2026-03-06")) == 0

    out = capsys.readouterr().out
    assert "Recognized words: 6" in out
    assert "Utterances: 2" in out


def test_a_reversed_day_range_is_refused_without_naming_the_database(stats_args, seed, capsys):
    seed(checkpoint())

    assert cmd_stats(stats_args("--since", "2026-03-06", "--until", "2026-03-04")) == 78

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "stenographer: analytics unavailable (ValueError). "
        "Check date filters and database access.\n"
    )


def test_export_delete_and_reset_each_reach_their_own_subcommand(stats_args, seed, capsys):
    seed(
        checkpoint("hotkey-1", source="hotkey", recognized_words=3),
        checkpoint("file-1", source="file", recognized_words=9),
    )

    assert cmd_stats(stats_args("export")) == 0
    exported = json.loads(capsys.readouterr().out)
    assert [record["id"] for record in exported["records"]] == ["hotkey-1"]

    assert cmd_stats(stats_args("delete")) == 0
    assert "Records selected for deletion: 1" in capsys.readouterr().out

    # reset ignores the source filter, so it counts the file-sourced record too.
    assert cmd_stats(stats_args("reset")) == 0
    assert "Records selected for deletion: 2" in capsys.readouterr().out


def test_a_corrupt_database_reports_only_the_failure_category(
    stats_args,
    analytics_home,
    capsys,
):
    analytics_home.parent.mkdir(parents=True)
    analytics_home.write_bytes(b"this is not a SQLite database\n")

    assert cmd_stats(stats_args()) == 78

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "analytics unavailable (DatabaseError)" in captured.err
    assert str(analytics_home) not in captured.err


def test_an_unusable_state_directory_reports_only_the_failure_category(
    stats_args,
    analytics_home,
    capsys,
):
    analytics_home.parent.parent.mkdir(parents=True)
    # A regular file where the state directory belongs: the store cannot create it.
    analytics_home.parent.write_text("not a directory\n", encoding="utf-8")

    assert cmd_stats(stats_args("delete", "--yes")) == 78

    captured = capsys.readouterr()
    # The preview reads an absent file as empty; only the write hits the failure.
    assert captured.out == "Records selected for deletion: 0\n"
    assert "analytics unavailable (FileExistsError)" in captured.err
    assert str(analytics_home) not in captured.err
