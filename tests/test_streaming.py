# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the streaming transcriber and bench WER (no real model)."""

from __future__ import annotations

import numpy as np

from stenographer.asr.model import WordInfo
from stenographer.asr.streaming import StreamingTranscriber, longest_common_prefix
from stenographer.bench import _parse_cardinal, word_error_rate

SR = 16000


class FakeModel:
    """Returns a scripted sequence of hypotheses, ignoring its audio input.

    Each scripted hypothesis is the *uncommitted tail* the streamer would see
    after the committed prefix is supplied as ``initial_prompt`` — i.e. what a
    real Whisper continuation returns.
    """

    def __init__(self, hypotheses: list[list[tuple[str, float, float]]]) -> None:
        self._hyps = hypotheses
        self._i = 0

    def transcribe_words(self, samples, *, beam_size=None, initial_prompt=None):
        hyp = self._hyps[min(self._i, len(self._hyps) - 1)]
        self._i += 1
        return [WordInfo(start=s, end=e, word=w, probability=1.0) for (w, s, e) in hyp]


def _sec(n: float) -> np.ndarray:
    return np.zeros(int(n * SR), dtype=np.float32)


# -- longest_common_prefix --------------------------------------------------


def test_lcp_basic() -> None:
    assert longest_common_prefix([[" the", " cat"], [" the", " dog"]]) == 1
    assert longest_common_prefix([[" the", " cat"], [" the", " cat"]]) == 2


def test_lcp_case_and_punctuation_insensitive() -> None:
    assert longest_common_prefix([["The,", "Cat."], [" the", " cat"]]) == 2


def test_lcp_edge_cases() -> None:
    assert longest_common_prefix([]) == 0
    assert longest_common_prefix([[], ["a"]]) == 0
    assert longest_common_prefix([["a"]]) == 1  # single hypothesis: whole thing


# -- StreamingTranscriber ---------------------------------------------------


def test_commits_only_agreeing_prefix() -> None:
    # Round 1 sees "A B C"; round 2 sees "A B X" -> commit the agreeing "A B".
    model = FakeModel(
        [
            [(" A", 0.0, 0.3), (" B", 0.3, 0.6), (" C", 0.6, 0.9)],
            [(" A", 0.0, 0.3), (" B", 0.3, 0.6), (" X", 0.6, 0.9)],
        ]
    )
    st = StreamingTranscriber(model, sample_rate=SR, agree=2)  # type: ignore[arg-type]

    r1 = st.push(_sec(1))
    assert r1.newly_committed == []  # not enough rounds yet
    assert r1.provisional == "A B C"

    r2 = st.push(_sec(1))
    assert [w.word.strip() for w in r2.newly_committed] == ["A", "B"]
    assert r2.committed_audio_ends == [0.3, 0.6]
    assert st.committed_text == "A B"
    assert r2.provisional == "X"


def test_revision_flag_tracks_provisional_change() -> None:
    model = FakeModel(
        [
            [(" hello", 0.0, 0.5), (" wold", 0.5, 1.0)],  # first guess (typo)
            [(" hello", 0.0, 0.5), (" world", 0.5, 1.0)],  # revised tail
        ]
    )
    st = StreamingTranscriber(model, sample_rate=SR, agree=2)  # type: ignore[arg-type]
    r1 = st.push(_sec(1))
    assert r1.revised is True and r1.provisional == "hello wold"
    r2 = st.push(_sec(1))
    # "hello" agrees across both rounds -> committed; tail revised wold->world.
    assert st.committed_text == "hello"
    assert r2.provisional == "world"
    assert r2.revised is True


def test_finish_flushes_remaining_tail() -> None:
    model = FakeModel([[(" one", 0.0, 0.5), (" two", 0.5, 1.0)]])
    st = StreamingTranscriber(model, sample_rate=SR, agree=2)  # type: ignore[arg-type]
    st.push(_sec(1))  # nothing committed (needs 2 rounds to agree)
    assert st.committed_text == ""
    final = st.finish()
    assert final == "one two"


def test_buffer_trims_after_commit() -> None:
    model = FakeModel(
        [
            [(" A", 0.0, 0.4)],
            [(" A", 0.0, 0.4)],
        ]
    )
    st = StreamingTranscriber(model, sample_rate=SR, agree=2)  # type: ignore[arg-type]
    st.push(_sec(1))
    st.push(_sec(1))
    # Two 1 s pushes = 2 s buffered; committing "A" (ends 0.4 s) trims 0.4 s off.
    assert st.committed_text == "A"
    assert st._buffer.shape[0] == int(2 * SR) - int(0.4 * SR)


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
