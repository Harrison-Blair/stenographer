# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for :class:`stenographer.output.formatter.HeuristicFormatter`."""

from __future__ import annotations

from stenographer.asr.model import SegmentInfo, WordInfo
from stenographer.config import Config, FormattingConfig
from stenographer.output.formatter import HeuristicFormatter


def _cfg(**overrides: object) -> FormattingConfig:
    defaults: dict[str, object] = {
        "paragraph_pause_seconds": 2.0,
        "capitalize_sentences": True,
        "normalize_spacing": True,
    }
    defaults.update(overrides)
    return FormattingConfig(**defaults)  # type: ignore[arg-type]


def _fmt(*, append_trailing_space: bool = False, **overrides: object) -> HeuristicFormatter:
    return HeuristicFormatter(_cfg(**overrides), append_trailing_space=append_trailing_space)


def _w(word: str, start: float, end: float) -> WordInfo:
    return WordInfo(start=start, end=end, word=word, probability=1.0)


# -- spacing -----------------------------------------------------------------


def test_first_word_has_no_leading_space() -> None:
    assert _fmt().feed([_w(" hello", 0.0, 0.5)]) == "Hello"


def test_words_joined_with_single_space() -> None:
    f = _fmt()
    out = f.feed([_w(" hello", 0.0, 0.5)]) + f.feed([_w(" world", 0.5, 1.0)])
    assert out == "Hello world"


def test_no_space_before_punctuation_token() -> None:
    f = _fmt()
    out = f.feed([_w(" hello", 0.0, 0.5), _w(",", 0.5, 0.6), _w(" world", 0.6, 1.0)])
    assert out == "Hello, world"


def test_double_spaces_collapse() -> None:
    f = _fmt(capitalize_sentences=False)
    out = f.feed([_w("  hello   there ", 0.0, 0.5), _w("  world", 0.5, 1.0)])
    assert out == "hello there world"


def test_normalize_spacing_false_passthrough() -> None:
    # Spacing is passed through verbatim, but normalize_spacing governs spacing
    # ONLY: capitalize_sentences is a separate knob and still applies.
    f = _fmt(normalize_spacing=False, capitalize_sentences=True)
    out = f.feed([_w(" hello", 0.0, 0.5), _w("  world.", 0.5, 1.0)])
    assert out == " Hello  world."


def test_normalize_spacing_false_leaves_spacing_untouched() -> None:
    f = _fmt(normalize_spacing=False, capitalize_sentences=False)
    out = f.feed([_w(" hello", 0.0, 0.5), _w("  world.", 0.5, 1.0)])
    assert out == " hello  world."  # tokens concatenated verbatim


def test_normalize_spacing_false_still_breaks_paragraphs() -> None:
    # paragraph_pause_seconds is independently configured; normalize_spacing
    # must not silently disable it.
    f = _fmt(normalize_spacing=False, capitalize_sentences=False, paragraph_pause_seconds=2.0)
    out = f.feed([_w("one.", 0.0, 0.5), _w("two", 3.0, 3.5)])
    assert "\n\n" in out


# -- paragraph breaks --------------------------------------------------------


def test_paragraph_break_on_long_pause() -> None:
    f = _fmt()
    out = f.feed([_w(" one.", 0.0, 0.5), _w(" two", 3.0, 3.5)])
    assert out == "One.\n\nTwo"


def test_no_paragraph_break_under_threshold() -> None:
    f = _fmt()
    out = f.feed([_w(" one.", 0.0, 0.5), _w(" two", 2.0, 2.5)])
    assert out == "One. Two"


def test_paragraph_pause_zero_disables_breaks() -> None:
    f = _fmt(paragraph_pause_seconds=0)
    out = f.feed([_w(" one", 0.0, 0.5), _w(" two", 30.0, 30.5)])
    assert out == "One two"


def test_no_paragraph_break_with_default_config() -> None:
    f = HeuristicFormatter(Config.defaults().formatting, append_trailing_space=False)
    out = f.feed([_w(" one", 0.0, 0.5), _w(" two", 5.0, 5.5)])
    assert "\n\n" not in out


def test_paragraph_break_still_available_via_explicit_config() -> None:
    f = _fmt(paragraph_pause_seconds=2.0)
    out = f.feed([_w(" one.", 0.0, 0.5), _w(" two", 3.0, 3.5)])
    assert out == "One.\n\nTwo"


def test_paragraph_break_capitalizes_next_word() -> None:
    f = _fmt()
    # No sentence terminal before the pause; the break itself capitalises.
    out = f.feed([_w(" one", 0.0, 0.5), _w(" two", 3.0, 3.5)])
    assert out == "One\n\nTwo"


# -- capitalisation ----------------------------------------------------------


def test_capitalize_after_sentence_terminals() -> None:
    f = _fmt()
    out = f.feed(
        [
            _w(" it", 0.0, 0.2),
            _w(" works.", 0.2, 0.4),
            _w(" really?", 0.4, 0.6),
            _w(" yes!", 0.6, 0.8),
            _w(" good", 0.8, 1.0),
        ]
    )
    assert out == "It works. Really? Yes! Good"


def test_no_capitalize_after_comma() -> None:
    f = _fmt()
    out = f.feed([_w(" well,", 0.0, 0.5), _w(" fine", 0.5, 1.0)])
    assert out == "Well, fine"


def test_lone_i_capitalized() -> None:
    f = _fmt()
    out = f.feed([_w(" so", 0.0, 0.2), _w(" i", 0.2, 0.4), _w(" think", 0.4, 0.6)])
    assert out == "So I think"


def test_capitalize_sentences_false_leaves_case_alone() -> None:
    f = _fmt(capitalize_sentences=False)
    out = f.feed([_w(" one.", 0.0, 0.5), _w(" i", 0.5, 0.7), _w(" two", 0.7, 1.0)])
    assert out == "one. i two"


# -- finalize / batch --------------------------------------------------------


def test_finalize_appends_trailing_space_and_resets() -> None:
    f = _fmt(append_trailing_space=True)
    out = f.feed([_w(" hi", 0.0, 0.5)]) + f.finalize()
    assert out == "Hi "
    # After reset the next utterance starts fresh (no leading space, capitalised).
    assert f.feed([_w(" again", 0.0, 0.5)]) == "Again"


def test_finalize_without_trailing_space() -> None:
    f = _fmt(append_trailing_space=False)
    assert f.feed([_w(" hi", 0.0, 0.5)]) + f.finalize() == "Hi"


def test_finalize_empty_utterance_emits_nothing() -> None:
    f = _fmt(append_trailing_space=True)
    assert f.finalize() == ""


def test_incremental_feed_equals_format_batch() -> None:
    words = [
        _w(" one", 0.0, 0.3),
        _w(" two.", 0.3, 0.6),
        _w(" three", 4.0, 4.3),
        _w(" four", 4.3, 4.6),
    ]
    f = _fmt(append_trailing_space=True)
    incremental = "".join(f.feed([w]) for w in words) + f.finalize()
    assert incremental == _fmt(append_trailing_space=True).format_batch(words)


def test_format_batch_accepts_segments() -> None:
    segments = [
        SegmentInfo(start=0.0, end=1.0, text=" hello there.", no_speech_prob=0.0),
        SegmentInfo(start=4.0, end=5.0, text=" new paragraph", no_speech_prob=0.0),
    ]
    out = _fmt(append_trailing_space=True).format_batch(segments)
    assert out == "Hello there.\n\nNew paragraph "
