# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading a reply, and refusing one that would ruin the paste."""

from __future__ import annotations

import json
import math

import pytest

from stenographer.lib.refine.errors import RefineRejectedError, RefineResponseError
from stenographer.lib.refine.prompt import RESPONSE_KEY
from stenographer.lib.refine.response import (
    MAX_LENGTH_RATIO,
    MIN_LENGTH_RATIO,
    guard,
    message_content,
    refined_text,
    restore_trailing_space,
    unwrap_structured,
)

ORIGINAL = "i think we should ship it on friday because the notes are not done"


def _reply(content: str) -> bytes:
    return json.dumps({"message": {"role": "assistant", "content": content}}).encode()


def test_content_comes_out_of_a_non_streaming_chat_reply():
    assert message_content(_reply("hello")) == "hello"


@pytest.mark.parametrize(
    "payload",
    [
        b"not json at all",
        b"[]",
        b'{"done": true}',
        b'{"message": "a string"}',
        b'{"message": {"role": "assistant"}}',
        b'{"message": {"content": 7}}',
    ],
)
def test_a_reply_that_is_not_a_chat_response_is_refused(payload):
    with pytest.raises(RefineResponseError):
        message_content(payload)


def test_structured_replies_yield_the_schema_field_and_plain_ones_pass_through():
    encoded = json.dumps({RESPONSE_KEY: "cleaned"})

    assert unwrap_structured(encoded, structured_output=True) == "cleaned"
    assert unwrap_structured("cleaned", structured_output=False) == "cleaned"


@pytest.mark.parametrize("content", ["not json", "[1, 2]", '{"other": "x"}', '{"text": 3}'])
def test_a_structured_reply_missing_its_field_is_refused(content):
    with pytest.raises(RefineResponseError):
        unwrap_structured(content, structured_output=True)


def test_a_plausible_edit_passes_the_guard_unchanged():
    candidate = "I think we should ship it on Friday, because the notes are not done."

    assert guard(ORIGINAL, candidate) == candidate


@pytest.mark.parametrize("candidate", ["", "   ", "\n"])
def test_empty_output_is_refused(candidate):
    with pytest.raises(RefineRejectedError):
        guard(ORIGINAL, candidate)


def test_the_floor_admits_a_correctly_collapsed_retracted_enumeration():
    """The benchmark measured 0.37-0.40 for the right answer on every model:
    dropping a retracted list item legitimately loses about a third of the
    words. Seen to FAIL against the original 0.40 floor."""
    # The benchmark's ``list_retract`` sample and what the default model
    # actually returned for it: ratio 0.38.
    spoken = (
        "so for the demo we need uh the slides the recording and the budget sheet "
        "actually no not the budget sheet just the slides and the recording"
    )
    cleaned = "So for the demo we need the slides and the recording."

    assert 0.30 <= len(cleaned) / len(spoken) < 0.40
    assert guard(spoken, cleaned) == cleaned


def test_output_far_shorter_than_the_input_is_refused_as_a_summary():
    summary = "x" * (math.ceil(len(ORIGINAL) * MIN_LENGTH_RATIO) - 1)

    with pytest.raises(RefineRejectedError):
        guard(ORIGINAL, summary)


def test_output_far_longer_than_the_input_is_refused_as_an_answer():
    answered = "x" * (math.floor(len(ORIGINAL) * MAX_LENGTH_RATIO) + 1)

    with pytest.raises(RefineRejectedError):
        guard(ORIGINAL, answered)


def test_the_length_band_is_inclusive_at_both_ends():
    shortest = "x" * math.ceil(len(ORIGINAL) * MIN_LENGTH_RATIO)
    longest = "x" * math.floor(len(ORIGINAL) * MAX_LENGTH_RATIO)

    assert guard(ORIGINAL, shortest) == shortest
    assert guard(ORIGINAL, longest) == longest


@pytest.mark.parametrize(
    ("wrapped", "inner"),
    [
        ('"{body}"', "{body}"),
        ("'{body}'", "{body}"),
        ("“{body}”", "{body}"),
        ("```\n{body}\n```", "{body}"),
        ("```text\n{body}\n```", "{body}"),
    ],
)
def test_one_wrapping_pair_is_stripped_rather_than_delivered(wrapped, inner):
    body = "I think we should ship it on Friday, the notes are not done."

    assert guard(ORIGINAL, wrapped.format(body=body)) == inner.format(body=body)


def test_a_second_wrapping_pair_is_a_refusal_not_another_strip():
    """A doubly wrapped reply was formatted, not edited; stripping again would
    hide that the model ignored the instruction not to add markdown."""
    body = "I think we should ship it on Friday, the notes are not done."

    with pytest.raises(RefineRejectedError):
        guard(ORIGINAL, f'```\n"{body}"\n```')


def test_an_empty_input_cannot_be_used_as_a_length_reference():
    with pytest.raises(RefineRejectedError):
        guard("   ", "anything at all")


def test_refined_text_parses_and_guards_in_one_step():
    cleaned = "I think we should ship it on Friday, because the notes are not done."
    payload = _reply(json.dumps({RESPONSE_KEY: cleaned}))

    assert refined_text(payload, ORIGINAL, structured_output=True) == cleaned


def test_the_dictation_trailing_space_survives_the_model():
    """``transcript_text`` adds it so consecutive pastes do not run together;
    a model that trims it would silently undo that for refined utterances."""
    assert restore_trailing_space("spoken words ", "Spoken words.") == "Spoken words. "
    assert restore_trailing_space("spoken words", "Spoken words.") == "Spoken words."
    assert restore_trailing_space("spoken words ", "Spoken words. ") == "Spoken words. "


def test_a_reply_cut_off_at_the_token_cap_is_refused():
    """``num_predict`` truncation yields a plausible-looking prefix that the
    length band can easily accept, so the only reliable signal is Ollama's own
    ``done_reason``. Delivering a half-sentence is worse than delivering the
    raw transcript. Seen to FAIL against a parser that ignored done_reason."""
    cut_off = "I think we should ship it on Friday because the notes are not"
    payload = json.dumps({"done_reason": "length", "message": {"content": cut_off}}).encode()

    with pytest.raises(RefineRejectedError):
        refined_text(payload, ORIGINAL, structured_output=False)


def test_a_reply_that_stopped_on_its_own_is_accepted():
    cleaned = "I think we should ship it on Friday, because the notes are not done."
    payload = json.dumps({"done_reason": "stop", "message": {"content": cleaned}}).encode()

    assert refined_text(payload, ORIGINAL, structured_output=False) == cleaned


def test_a_reply_with_no_done_reason_is_not_treated_as_truncated():
    """Not every Ollama build reports one; absence must not fail the stage."""
    cleaned = "I think we should ship it on Friday, because the notes are not done."
    payload = json.dumps({"message": {"content": cleaned}}).encode()

    assert refined_text(payload, ORIGINAL, structured_output=False) == cleaned


def test_quotation_marks_inside_the_text_are_not_mistaken_for_a_wrapper():
    """Dictating dialogue produces text that starts and ends with a quote
    without being quoted. Stripping those two characters silently corrupts the
    paste. Seen to FAIL against a naive startswith/endswith strip."""
    spoken = "he said we are done and then he said lets go home right now okay"
    dialogue = '"We are done," he said, and then, "let\'s go home."'

    assert guard(spoken, dialogue) == dialogue


def test_an_apostrophe_at_each_end_is_not_a_single_quote_wrapper():
    spoken = "tis the season and the dogs bowl is empty so fill it up please now"
    text = "'tis the season, and the dog's bowl is empty, so fill it up'"

    assert guard(spoken, text) == text


def test_a_genuinely_quoted_reply_is_still_unwrapped():
    body = "I think we should ship it on Friday, the notes are not done."

    assert guard(ORIGINAL, f'"{body}"') == body
    assert guard(ORIGINAL, f"“{body}”") == body
