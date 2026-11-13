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


def _lines(count: int, words: int = 10) -> list[str]:
    """``count`` lines; line ``n`` holds ``words`` words ``wN``, so a sample shows its lines."""
    return [" ".join([f"w{index}"] * words) for index in range(count)]


def _reply(content: str, **extra) -> bytes:
    return json.dumps({"message": {"role": "assistant", "content": content}, **extra}).encode()


# Samples


def test_an_empty_transcript_gives_no_text():
    assert transcript_samples([]) == ""
    assert transcript_samples(["", "   "]) == ""


def test_a_transcript_of_at_most_1800_words_is_sent_whole():
    lines = _lines(180)
    assert transcript_samples(lines) == "\n".join(lines)


def test_a_longer_transcript_gives_600_words_from_the_start_the_middle_and_the_end():
    # 181 lines of 10 words: 1810 words, so three samples of 60 lines.
    lines = _lines(181)
    start, middle, end = transcript_samples(lines).split("\n[…]\n")
    assert start == "\n".join(lines[0:60])
    # The middle line is 90; the sample takes 90, 91, 89, 92, 88, ... until 600 words:
    # 30 lines after 90 and 29 before it.
    assert middle == "\n".join(lines[61:121])
    assert end == "\n".join(lines[121:181])


def test_each_sample_takes_whole_lines_until_it_has_600_words():
    # Lines of 250 words: three lines (750 words) reach 600, two (500) do not.
    lines = _lines(20, words=250)
    samples = transcript_samples(lines).split("\n[…]\n")
    assert [len(sample.split()) for sample in samples] == [750, 750, 750]
    assert samples[0] == "\n".join(lines[0:3])
    assert samples[1] == "\n".join(lines[9:12])
    assert samples[2] == "\n".join(lines[17:20])


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
    assert timeout > 0


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
