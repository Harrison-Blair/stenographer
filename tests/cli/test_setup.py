# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure decision and prompt parsing tests for interactive setup."""

from __future__ import annotations

import io

import pytest

from stenographer.cli import setup
from stenographer.cli.setup import (
    followup_exit_code,
    parse_bool,
    parse_choice,
    parse_number,
    parse_optional_string,
    parse_quick_review_action,
    parse_review_action,
    restart_eligible,
)


def test_optional_string_retains_clears_and_replaces():
    assert parse_optional_string("", "current") == "current"
    assert parse_optional_string(" clear ", "current") is None
    assert parse_optional_string("replacement", None) == "replacement"


def test_choice_retains_and_is_case_insensitive():
    assert parse_choice("", "hold", ("hold", "toggle")) == "hold"
    assert parse_choice("TOGGLE", "hold", ("hold", "toggle")) == "toggle"
    with pytest.raises(ValueError, match="choose one of"):
        parse_choice("hybrid", "hold", ("hold", "toggle"))


@pytest.mark.parametrize(("answer", "expected"), [("yes", True), ("N", False), ("", True)])
def test_bool_answers(answer, expected):
    assert parse_bool(answer, True) is expected


def test_bool_rejects_ambiguous_answer():
    with pytest.raises(ValueError, match="yes or no"):
        parse_bool("maybe", False)


def test_number_retains_and_enforces_type_and_range():
    assert parse_number("", 3, minimum=1, maximum=10, integer=True) == 3
    assert parse_number("4", 3, minimum=1, maximum=10, integer=True) == 4
    assert parse_number(".25", 0.5, minimum=0.0, maximum=1.0) == 0.25
    with pytest.raises(ValueError, match="must be in"):
        parse_number("11", 3, minimum=1, maximum=10, integer=True)
    with pytest.raises(ValueError, match="integer"):
        parse_number("1.5", 3, minimum=1, maximum=10, integer=True)


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("", "save"),
        ("cancel", "cancel"),
        ("1", "hotkey"),
        ("2", "audio"),
        ("3", "asr"),
        ("4", "feedback"),
    ],
)
def test_review_actions(answer, expected):
    assert parse_review_action(answer) == expected


def test_review_rejects_unknown_action():
    with pytest.raises(ValueError, match="Save, Cancel"):
        parse_review_action("later")


@pytest.mark.parametrize(
    ("answer", "expected"), [("", "save"), ("S", "save"), ("cancel", "cancel")]
)
def test_quick_review_actions(answer, expected):
    assert parse_quick_review_action(answer) == expected


def test_quick_review_rejects_reedit_actions():
    with pytest.raises(ValueError, match="Save or Cancel"):
        parse_quick_review_action("audio")


@pytest.mark.parametrize(
    ("changed", "custom", "missing", "active", "expected"),
    [
        (True, False, False, "active", True),
        (False, False, False, "active", False),
        (True, True, False, "active", False),
        (True, False, True, "active", False),
        (True, False, False, "inactive", False),
        (True, False, False, None, False),
    ],
)
def test_restart_eligibility(changed, custom, missing, active, expected):
    assert (
        restart_eligible(
            config_changed=changed,
            custom_config=custom,
            missing_required=missing,
            service_active=active,
        )
        is expected
    )


@pytest.mark.parametrize(
    ("operational", "missing", "expected"),
    [(False, False, 0), (False, True, 78), (True, False, 1), (True, True, 1)],
)
def test_followup_exit_precedence(operational, missing, expected):
    assert followup_exit_code(operational_failure=operational, missing_required=missing) == expected


def test_setup_requires_an_interactive_terminal():
    stderr = io.StringIO()
    assert setup.run(stdin=io.StringIO(), stdout=io.StringIO(), stderr=stderr) == 2
    assert "requires an interactive terminal" in stderr.getvalue()
