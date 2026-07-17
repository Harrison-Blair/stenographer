# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the LocalAgreement committer (no model, no audio)."""

from __future__ import annotations

import pytest

from stenographer.asr.model import WordInfo
from stenographer.asr.streaming import (
    StreamingTranscriber,
    longest_common_prefix,
)


def _words(*tokens: tuple[str, float, float]) -> list[WordInfo]:
    return [WordInfo(start=s, end=e, word=w, probability=1.0) for w, s, e in tokens]


# -- longest_common_prefix ---------------------------------------------------


def test_lcp_basic() -> None:
    assert longest_common_prefix([[" the", " cat"], [" the", " dog"]]) == 1
    assert longest_common_prefix([[" the", " cat"], [" the", " cat"]]) == 2


def test_lcp_case_insensitive_but_punctuation_sensitive() -> None:
    # Casing is owned by the formatter, so "The"/"the" agree...
    assert longest_common_prefix([["The", "Cat"], [" the", " cat"]]) == 2
    # ...but punctuation is part of the typed surface, so it must match.
    assert longest_common_prefix([["world."], ["world"]]) == 0
    assert longest_common_prefix([["hello,", "world."], ["hello,", "world"]]) == 1


def test_lcp_edge_cases() -> None:
    assert longest_common_prefix([]) == 0
    assert longest_common_prefix([[], ["a"]]) == 0
    assert longest_common_prefix([["a"]]) == 1


# -- StreamingTranscriber ----------------------------------------------------


def test_agreement_n_validated() -> None:
    with pytest.raises(ValueError):
        StreamingTranscriber(agreement_n=0)


def test_commits_only_agreeing_prefix() -> None:
    st = StreamingTranscriber(agreement_n=2)
    r1 = st.insert(_words((" A", 0.0, 0.3), (" B", 0.3, 0.6), (" C", 0.6, 0.9)))
    assert r1 == []  # first hypothesis: nothing to agree with yet
    r2 = st.insert(_words((" A", 0.0, 0.3), (" B", 0.3, 0.6), (" X", 0.6, 0.9)))
    assert [w.word for w in r2] == [" A", " B"]
    assert st.committed_text == "A B"


def test_punctuation_blocks_premature_commit() -> None:
    # "world" must not be committed while its punctuation is still unstable.
    st = StreamingTranscriber(agreement_n=2)
    st.insert(_words((" world", 0.0, 0.5)))
    r2 = st.insert(_words((" world.", 0.0, 0.5)))
    assert r2 == []
    r3 = st.insert(_words((" world.", 0.0, 0.5)))
    assert [w.word for w in r3] == [" world."]


def test_flush_commits_residual_tail() -> None:
    st = StreamingTranscriber(agreement_n=2)
    st.insert(_words((" one", 0.0, 0.5), (" two", 0.5, 1.0)))
    assert st.committed_text == ""
    tail = st.flush()
    assert [w.word for w in tail] == [" one", " two"]
    assert st.committed_text == "one two"


def test_committed_prefix_never_revised() -> None:
    st = StreamingTranscriber(agreement_n=2)
    st.insert(_words((" hello", 0.0, 0.5)))
    st.insert(_words((" hello", 0.0, 0.5)))
    assert st.committed_text == "hello"
    # Later hypotheses that disagree with the committed region are ignored.
    st.insert(_words((" yellow", 0.0, 0.5), (" world", 0.5, 1.0)))
    st.insert(_words((" yellow", 0.0, 0.5), (" world", 0.5, 1.0)))
    assert st.committed_text == "hello world"


def test_committed_prefix_skipped_by_time_under_retokenization() -> None:
    st = StreamingTranscriber(agreement_n=2)
    st.insert(_words((" ice", 0.0, 0.4), (" cream", 0.4, 0.8)))
    st.insert(_words((" ice", 0.0, 0.4), (" cream", 0.4, 0.8)))
    assert st.committed_text == "ice cream"
    # A re-decode retokenises the committed audio as one word; only words
    # past the committed end-time count as tail.
    r = st.insert(_words((" icecream", 0.0, 0.8), (" cone", 0.8, 1.2)))
    assert r == []
    r = st.insert(_words((" icecream", 0.0, 0.8), (" cone", 0.8, 1.2)))
    assert [w.word for w in r] == [" cone"]
    assert st.committed_text == "ice cream cone"


def test_rebase_shifts_subsequent_commits_to_absolute_time() -> None:
    st = StreamingTranscriber(agreement_n=2)
    st.insert(_words((" first.", 0.0, 1.0)))
    committed = st.insert(_words((" first.", 0.0, 1.0)))
    assert committed[0].end == 1.0
    # Driver trims the first 1.0 s off the window.
    st.rebase(1.0)
    st.insert(_words((" second", 0.5, 1.0)))
    committed = st.insert(_words((" second", 0.5, 1.0)))
    assert committed[0].start == 1.5  # 0.5 window-local + 1.0 offset
    assert committed[0].end == 2.0
    assert st.committed_text == "first. second"


def test_reset_clears_all_state() -> None:
    st = StreamingTranscriber(agreement_n=2)
    st.insert(_words((" a", 0.0, 0.5)))
    st.insert(_words((" a", 0.0, 0.5)))
    st.rebase(2.0)
    st.reset()
    assert st.committed_text == ""
    assert st.committed_words == []
    st.insert(_words((" b", 0.0, 0.5)))
    committed = st.insert(_words((" b", 0.0, 0.5)))
    assert committed[0].start == 0.0  # offset was reset
