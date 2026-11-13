# SPDX-License-Identifier: GPL-3.0-or-later
"""The title request: samples of the transcript, the request body, and the reply check."""

from __future__ import annotations

import json

import pytest

from stenographer.lib.refine.errors import RefineRejectedError, RefineTransportError
from stenographer.lib.refine.title import (
    build_title_body,
    request_title,
    title_from_reply,
    transcript_samples,
)


def _reply(content: str, **extra) -> bytes:
    return json.dumps({"message": {"role": "assistant", "content": content}, **extra}).encode()


# Samples


def test_an_empty_transcript_gives_no_text():
    assert transcript_samples([]) == ""
    assert transcript_samples(["", "   "]) == ""


def test_a_transcript_of_at_most_1800_words_is_sent_whole():
    lines = _numbered(*[10] * 180)
    assert transcript_samples(lines) == "\n".join(lines)


def _numbered(*counts: int) -> list[str]:
    """Lines of ``counts`` words; every word ``nK`` holds its own word position ``K``."""
    lines, position = [], 0
    for count in counts:
        lines.append(" ".join(f"n{position + index}" for index in range(count)))
        position += count
    return lines


def _positions(sample: str) -> list[int]:
    return [int(word[1:]) for word in sample.split()]


def _three(lines: list[str]) -> list[list[int]]:
    samples = transcript_samples(lines).split("\n[…]\n")
    assert len(samples) == 3
    return [_positions(sample) for sample in samples]


def test_exactly_1800_words_are_sent_whole():
    lines = _numbered(*[100] * 18)
    assert transcript_samples(lines) == "\n".join(lines)


def test_1801_words_give_three_samples_of_600_words_by_word_position():
    start, middle, end = _three(_numbered(*[100] * 18, 1))
    assert start == list(range(0, 600))
    # The middle word is 900: 300 words before it and 300 from it.
    assert middle == list(range(600, 1200))
    assert end == list(range(1201, 1801))


def test_one_line_of_2001_words_gives_three_different_samples():
    start, middle, end = _three(_numbered(2001))
    assert start == list(range(0, 600))
    assert middle == list(range(700, 1300))
    assert end == list(range(1401, 2001))


def test_a_long_line_between_short_lines_gives_samples_that_share_no_word():
    # 30 lines of 10 words, one line of 1500 words, 30 lines of 10 words: 2100 words.
    start, middle, end = _three(_numbered(*[10] * 30, 1500, *[10] * 30))
    assert [len(start), len(middle), len(end)] == [600, 600, 600]
    assert start == list(range(0, 600))
    assert middle == list(range(750, 1350))
    assert end == list(range(1500, 2100))
    assert not (set(start) & set(middle) or set(middle) & set(end) or set(start) & set(end))


def test_a_sample_keeps_the_line_breaks_of_its_words():
    lines = _numbered(*[10] * 181)
    start = transcript_samples(lines).split("\n[…]\n")[0]
    assert start == "\n".join(lines[0:60])


# The request body


def test_the_body_has_the_model_no_thinking_temperature_0_a_reply_limit_and_no_context_size():
    body = build_title_body("You: the venue", model="gemma4:e2b", keep_alive=900)
    assert body["model"] == "gemma4:e2b"
    assert body["stream"] is False
    assert body["think"] is False
    assert body["keep_alive"] == 900
    assert body["options"] == {"temperature": 0, "num_predict": 40}
    assert "num_ctx" not in json.dumps(body)
    messages = body["messages"]
    assert [message["role"] for message in messages] == ["system", "user"]
    assert messages[1]["content"] == "You: the venue"


def test_request_title_posts_the_body_to_the_host_and_returns_the_title():
    posted = []

    def post(host, body, *, timeout):
        posted.append((host, body, timeout))
        return _reply("  Venue booking, deposit \n")

    title = request_title(
        "http://127.0.0.1:11434", "gemma4:e2b", "You: the venue", keep_alive=-1, post=post
    )
    assert title == "Venue booking, deposit"
    [(host, body, timeout)] = posted
    assert host == "http://127.0.0.1:11434"
    assert body == build_title_body("You: the venue", model="gemma4:e2b", keep_alive=-1)
    assert timeout == 150.0


def test_request_title_passes_a_transport_failure_on():
    def post(host, body, *, timeout):
        raise RefineTransportError("ollama could not be reached")

    with pytest.raises(RefineTransportError):
        request_title("http://127.0.0.1:11434", "m", "text", keep_alive=1, post=post)


# The reply check


def test_a_one_line_reply_of_80_characters_is_the_title():
    title = "x" * 80
    assert title_from_reply(_reply(f"\n {title} \n")) == title


@pytest.mark.parametrize(
    "content",
    ["x" * 81, "Venue booking\nDeposit", "", "  \n "],
    ids=["81-characters", "two-lines", "empty", "white-space"],
)
def test_a_reply_that_is_not_one_line_of_at_most_80_characters_is_discarded(content):
    with pytest.raises(RefineRejectedError) as error:
        title_from_reply(_reply(content))
    # The reason never quotes the reply.
    assert content.strip() == "" or content.strip()[:5] not in str(error.value)


def test_a_reply_cut_at_the_reply_limit_is_discarded():
    with pytest.raises(RefineRejectedError):
        title_from_reply(_reply("Venue booking", done_reason="length"))
