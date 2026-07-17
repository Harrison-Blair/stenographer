# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the bench WER / number-normalisation helpers (no real model)."""

from __future__ import annotations

from stenographer.bench import _parse_cardinal, word_error_rate

# -- word_error_rate --------------------------------------------------------


def test_wer_identical() -> None:
    assert word_error_rate("the cat sat", "the cat sat") == 0.0


def test_wer_case_and_punctuation_insensitive() -> None:
    assert word_error_rate("The cat, sat.", "the cat sat") == 0.0


def test_wer_one_substitution() -> None:
    assert word_error_rate("the cat sat", "the dog sat") == 1 / 3


def test_wer_deletion() -> None:
    assert word_error_rate("the cat sat", "the sat") == 1 / 3


def test_wer_empty_reference() -> None:
    assert word_error_rate("", "") == 0.0
    assert word_error_rate("", "hello") == 1.0


# -- number normalization ---------------------------------------------------


def test_parse_cardinal_basic() -> None:
    assert _parse_cardinal(["three"]) == "3"
    assert _parse_cardinal(["twenty", "six"]) == "26"
    assert _parse_cardinal(["one", "hundred"]) == "100"
    assert _parse_cardinal(["five", "thousand"]) == "5000"


def test_parse_cardinal_year_and_decimal_and_sequence() -> None:
    assert _parse_cardinal(["twenty", "twenty", "six"]) == "2026"  # year
    assert _parse_cardinal(["nineteen", "eighty", "four"]) == "1984"  # year
    assert _parse_cardinal(["twelve", "point", "five"]) == "12.5"  # decimal
    assert _parse_cardinal(["one", "two", "three"]) == "123"  # digit sequence


def test_wer_number_words_match_digits() -> None:
    # "twenty twenty six" == "2026", "twelve point five" == "12.5": no word errors.
    assert word_error_rate("in twenty twenty six", "in 2026") == 0.0
    assert word_error_rate("about twelve point five ounces", "about 12.5 ounces") == 0.0
