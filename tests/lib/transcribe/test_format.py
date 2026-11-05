# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for the fixed transcript formatter."""

from __future__ import annotations

import pytest

from stenographer.lib.transcribe.format import format_transcript


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", ""),
        ("   ", ""),
        ("\t\n ", ""),
        ("hello    world", "Hello world"),
        ("hello , world . ok ; yes : no !", "Hello, world. Ok; yes: no!"),
        ("hello there. how are you? fine.", "Hello there. How are you? Fine."),
        ("okay then", "Okay then"),
        ("then i went", "Then I went"),
        ("i think", "I think"),
        ("then (i), and “i” spoke", "Then (I), and “I” spoke"),
        ("then i.e. and i2", "Then i.e. And i2"),
        ("put it in there", "Put it in there"),
        ("123 go", "123 go"),
        ("42. go", "42. Go"),
    ],
)
def test_format_transcript(text, expected):
    assert format_transcript(text) == expected


def test_trailing_space_option():
    assert format_transcript("hi", trailing_space=True) == "Hi "
    assert format_transcript("hi") == "Hi"
    assert format_transcript("", trailing_space=True) == ""
