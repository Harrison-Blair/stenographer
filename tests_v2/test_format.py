# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for the fixed transcript formatter."""

from __future__ import annotations

from stenographer_v2.format import format_transcript


def test_empty_and_whitespace_only():
    assert format_transcript("") == ""
    assert format_transcript("   ") == ""
    assert format_transcript("\t\n ") == ""


def test_collapses_runs_of_spaces():
    assert format_transcript("hello    world") == "Hello world"


def test_no_space_before_closing_punctuation():
    assert format_transcript("hello , world . ok ; yes : no !") == "Hello, world. Ok; yes: no!"


def test_capitalizes_sentence_starts():
    assert format_transcript("hello there. how are you? fine.") == "Hello there. How are you? Fine."


def test_first_character_capitalized():
    assert format_transcript("okay then") == "Okay then"


def test_standalone_i_becomes_capital():
    assert format_transcript("then i went") == "Then I went"
    assert format_transcript("i think") == "I think"


def test_in_is_not_rewritten():
    assert format_transcript("put it in there") == "Put it in there"


def test_trailing_space_option():
    assert format_transcript("hi", trailing_space=True) == "Hi "
    assert format_transcript("hi") == "Hi"
    assert format_transcript("", trailing_space=True) == ""
