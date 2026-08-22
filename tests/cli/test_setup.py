# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure decision and prompt parsing tests for interactive setup."""

from __future__ import annotations

import io

import pytest

from stenographer.cli import setup
from stenographer.cli.binding_capture import CaptureState, KeyEvent, reduce_capture
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


def _capture(*events: KeyEvent | None) -> CaptureState:
    state = CaptureState()
    for event in events:
        state = reduce_capture(state, event)
    return state


def test_binding_capture_completes_a_single_key_after_release():
    pressed = _capture(KeyEvent("kbd", 97, 1))
    assert pressed.codes == (97,)
    assert pressed.complete is False

    released = reduce_capture(pressed, KeyEvent("kbd", 97, 0))
    assert released.complete is True
    assert released.held == frozenset()


def test_binding_capture_keeps_press_order_and_ignores_repeats():
    state = _capture(
        KeyEvent("kbd", 29, 1),
        KeyEvent("kbd", 29, 2),
        KeyEvent("kbd", 30, 1),
    )

    assert state.codes == (29, 30)
    assert state.held == frozenset({("kbd", 29), ("kbd", 30)})


def test_binding_capture_completes_after_reverse_release_order():
    state = _capture(
        KeyEvent("kbd", 29, 1),
        KeyEvent("kbd", 30, 1),
        KeyEvent("kbd", 30, 0),
    )
    assert state.complete is False

    state = reduce_capture(state, KeyEvent("kbd", 29, 0))
    assert state.complete is True


def test_binding_capture_unions_held_keys_across_devices():
    state = _capture(
        KeyEvent("left", 29, 1),
        KeyEvent("right", 30, 1),
        KeyEvent("left", 29, 0),
    )
    assert state.codes == (29, 30)
    assert state.complete is False

    state = reduce_capture(state, KeyEvent("right", 30, 0))
    assert state.complete is True


def test_binding_capture_waits_for_same_code_held_on_another_device():
    state = _capture(
        KeyEvent("left", 97, 1),
        KeyEvent("right", 97, 1),
        KeyEvent("left", 97, 0),
    )
    assert state.codes == (97,)
    assert state.complete is False

    state = reduce_capture(state, KeyEvent("right", 97, 0))
    assert state.complete is True


def test_binding_capture_timeout_is_terminal():
    state = _capture(KeyEvent("kbd", 29, 1), None)
    assert state.timed_out is True
    assert state.complete is False

    assert reduce_capture(state, KeyEvent("kbd", 29, 0)) == state
