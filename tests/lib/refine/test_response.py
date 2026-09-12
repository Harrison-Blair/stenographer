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


# --- Numerals must come through untouched ---------------------------------------


@pytest.mark.parametrize(
    ("spoken", "candidate"),
    [
        # The default model's one measured blemish: a lone digit written as a word.
        (
            "the rtx 3080 only has 8 gigabytes of vram",
            "The RTX 3080 only has eight gigabytes of VRAM.",
        ),
        # qwen3:4b under a schema: punctuation injected into a digit string.
        ("so i benchmarked it on the rtx 3080", "So I benchmarked it on the RTX 3:080."),
        # A spelled-out time turned into digits is an addition the speaker never made.
        ("i think it moved to nine thirty", "I think it moved to 9:30."),
        # A version string reformatted, and a number invented.
        ("we are on version 0.12.3 now", "We are on version 0.12.3 now, build 1204."),
        # A number the speaker said once, delivered twice.
        (
            "port 8080 is taken so pick another one for the dev server please",
            "Port 8080 is taken, so pick 8080 for the dev server, please.",
        ),
    ],
)
def test_output_that_changes_a_number_is_refused(spoken, candidate):
    """Seen to FAIL before the numeral guard existed: every candidate here is
    inside the length band, unwrapped, and non-empty, so nothing else stops it."""
    with pytest.raises(RefineRejectedError):
        guard(spoken, candidate)


def test_numbers_kept_verbatim_pass_the_guard():
    spoken = (
        "okay so the sync is at 4:15 and only 8 people have replied which is like 20% of "
        "the team um and we are on version 0.12.3 with 1,204 rows"
    )
    cleaned = (
        "Okay, so the sync is at 4:15 and only 8 people have replied, which is 20% of "
        "the team, and we are on version 0.12.3 with 1,204 rows."
    )

    assert guard(spoken, cleaned) == cleaned


def test_reordered_numbers_still_pass_when_each_survives():
    """The guard compares what numbers appear, not where; a correct paragraph
    split or clause reorder must not trip it."""
    spoken = "ping me at 3 and then at 5 about the 2 tickets"
    cleaned = "About the 2 tickets: ping me at 3, and then at 5."

    assert guard(spoken, cleaned) == cleaned


@pytest.mark.parametrize(
    ("spoken", "cleaned"),
    [
        # Each is a real corpus sample and the correct cleanup for it. Seen to
        # FAIL against strict numeral equality, which refused all of them.
        ("lets meet at 3 no wait 4 in the small room", "Let's meet at 4 in the small room."),
        (
            "i tagged version 0.12.2 sorry 0.12.3 this morning",
            "I tagged version 0.12.3 this morning.",
        ),
        ("can you buy 2 of them actually 3 of them", "Can you buy 3 of them?"),
        (
            "we need 3 mics 2 stands and 4 cables actually not the cables",
            "We need:\n- 3 mics\n- 2 stands",
        ),
        ("the meeting is at 6 in the main hall no wait 7", "The meeting is at 7 in the main hall."),
        ("lets do it at 2 no 3 no wait 4", "Let's do it at 4."),
        ("it costs 40 dollars i mean 45 for the pair", "It costs 45 for the pair."),
    ],
)
def test_a_number_the_speaker_took_back_may_be_dropped(spoken, cleaned):
    assert guard(spoken, cleaned) == cleaned


def test_a_correction_marker_is_permission_not_an_order():
    """A marker after a number lets the model drop it; keeping it is fine too."""
    spoken = "lets meet at 3 no wait 4 in the small room"
    kept = "Let's meet at 3, no wait, 4 in the small room."

    assert guard(spoken, kept) == kept


def test_the_number_kept_must_be_the_one_the_speaker_settled_on():
    """The default model really produced this: it kept the abandoned time and
    deleted the settled one. Nothing follows 9:30 in the input, so its
    disappearance is unjustified and the raw text is delivered instead."""
    spoken = "standup moved to 9:15 no 9:30"
    wrong = "Standup moved to 9:15."

    with pytest.raises(RefineRejectedError):
        guard(spoken, wrong)


@pytest.mark.parametrize(
    ("spoken", "candidate"),
    [
        # A dropped time with no correction anywhere.
        (
            "so the build finished at 4:15 and the tests went green at 4:40",
            "So the build finished at 4:15 and the tests went green.",
        ),
        # The same number said twice, delivered once.
        (
            "the daemon listens on port 8080 and the overlay talks to 8080 from the other side",
            "The daemon listens on port 8080, and the overlay talks to it from the other side.",
        ),
        # "not" and "wait" are not correction markers.
        (
            "i need 3 items not counting the 4 spares in the box",
            "I need items, not counting the 4 spares in the box.",
        ),
        ("wait until 6 and then send the 2 files", "Wait until then and send the 2 files."),
        # A marker too far after the number to have been about it.
        (
            "the room holds 40 people and the projector is broken so actually lets use the annex",
            "The room holds people and the projector is broken, so let's use the annex.",
        ),
    ],
)
def test_a_number_dropped_without_a_spoken_correction_is_refused(spoken, candidate):
    with pytest.raises(RefineRejectedError):
        guard(spoken, candidate)


def test_a_marker_still_counts_when_the_number_carries_punctuation():
    spoken = "the sync is at 4:15, no, 4:30, in the small room"
    cleaned = "The sync is at 4:30 in the small room."

    assert guard(spoken, cleaned) == cleaned


def test_a_retraction_licenses_one_drop_not_every_copy_of_that_number():
    spoken = "it is 30 kilometers actually about 30 miles and 30 is the limit"
    both_dropped = "It is about miles, and the limit."

    with pytest.raises(RefineRejectedError):
        guard(spoken, both_dropped)
