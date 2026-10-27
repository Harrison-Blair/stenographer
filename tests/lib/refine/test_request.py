# SPDX-License-Identifier: GPL-3.0-or-later
"""The wire body of the one request the refine stage makes.

Shape, not wording: the prompt text and the default model are benchmark
property and may change under these tests without breaking them. What must not
change silently is that the request is non-streaming, non-thinking,
zero-temperature, capped, and carries the schema exactly when structured output
is on.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from stenographer.lib.refine.profiles import RefineProfile
from stenographer.lib.refine.prompt import (
    FEW_SHOT_EXAMPLES,
    NUM_PREDICT_BASE,
    NUM_PREDICT_MAX,
    NUM_PREDICT_PER_WORD,
    RESPONSE_KEY,
    RESPONSE_SCHEMA,
    SYSTEM_PROMPT,
)
from stenographer.lib.refine.request import (
    build_chat_body,
    build_messages,
    build_unload_body,
    build_warm_body,
    encode,
    num_predict_for,
)


def _body(**overrides):
    kwargs = {
        "model": "test-model",
        "words": 12,
        "keep_alive": 900,
        "structured_output": True,
    }
    kwargs.update(overrides)
    return build_chat_body("some spoken words here", **kwargs)


def test_request_is_a_single_shot_zero_temperature_edit():
    body = _body()

    assert body["model"] == "test-model"
    assert body["stream"] is False
    assert body["think"] is False
    assert body["keep_alive"] == 900
    assert body["options"]["temperature"] == 0


def test_num_predict_scales_with_the_input_then_stops():
    assert num_predict_for(0) == NUM_PREDICT_BASE
    assert num_predict_for(12) == NUM_PREDICT_BASE + 12 * NUM_PREDICT_PER_WORD
    assert _body(words=12)["options"]["num_predict"] == num_predict_for(12)


def test_num_predict_never_exceeds_the_ceiling_however_long_the_dictation():
    """A model that starts looping must not be able to spend the whole time
    budget doing it, so the cap has a hard upper bound as well as a slope."""
    saturating = (NUM_PREDICT_MAX - NUM_PREDICT_BASE) // NUM_PREDICT_PER_WORD

    assert num_predict_for(saturating) == NUM_PREDICT_MAX
    assert num_predict_for(saturating + 1) == NUM_PREDICT_MAX
    assert num_predict_for(100_000) == NUM_PREDICT_MAX


def test_the_cap_leaves_real_headroom_over_measured_output():
    """Measured output is about ``1.15 * words + 8`` tokens. Truncation yields a
    short reply the length guard may not catch, so the cap must not cut fine."""
    for words in (10, 50, 155, 300):
        assert num_predict_for(words) > 1.15 * words + 8


def test_schema_travels_only_with_structured_output():
    assert _body(structured_output=True)["format"] == RESPONSE_SCHEMA
    assert "format" not in _body(structured_output=False)


def test_messages_are_system_then_every_example_then_the_utterance():
    messages = build_messages("clean me up please", structured_output=False)

    assert messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert len(messages) == 1 + 2 * len(FEW_SHOT_EXAMPLES) + 1
    assert messages[-1] == {"role": "user", "content": "clean me up please"}
    assert [m["role"] for m in messages[1:-1]] == ["user", "assistant"] * len(FEW_SHOT_EXAMPLES)


def test_example_answers_are_shown_in_the_format_the_reply_will_use():
    """A few-shot answer in plain text while the grammar demands JSON teaches
    the model the wrong shape; the example half has to follow the format."""
    plain = build_messages("x", structured_output=False)
    structured = build_messages("x", structured_output=True)
    spoken, cleaned = FEW_SHOT_EXAMPLES[0]

    assert plain[2]["content"] == cleaned
    assert json.loads(structured[2]["content"]) == {RESPONSE_KEY: cleaned}
    assert plain[1]["content"] == structured[1]["content"] == spoken


def test_the_utterance_is_the_only_place_the_transcript_appears():
    body = _body()
    rendered = encode(body).decode("utf-8")
    utterance = "some spoken words here"

    assert rendered.count(utterance) == 1
    assert body["messages"][-1]["content"] == utterance


def test_warm_and_unload_generate_nothing_at_all():
    warm = build_warm_body(model="m", keep_alive=-1)
    unload = build_unload_body(model="m")

    assert warm["prompt"] == "" and warm["options"]["num_predict"] == 0
    assert warm["keep_alive"] == -1
    assert unload["keep_alive"] == 0


def test_encode_is_the_exact_bytes_that_go_on_the_wire():
    assert json.loads(encode({"a": 1})) == {"a": 1}


#: SHA-256 of the wire body captured at the base commit (51c4537), before the
#: vocabulary existed, for ``alpha bravo charlie delta echo`` with
#: ``test-model``, 5 words and ``keep_alive`` 900. An empty vocabulary must
#: keep every one of them byte-for-byte.
_BASE_BODY_SHA256 = {
    (RefineProfile.AGENT, True): (
        "81e70414d32edee725d17bed90d0ff348bba1bc37e87ec5de5e1e3d6b7a3c621"
    ),
    (RefineProfile.AGENT, False): (
        "2042ef474e8f8655de7b7391b09c800c514c4af3441261765bc305f104a5ee77"
    ),
    (RefineProfile.GENERAL, True): (
        "1d36dbf13d6cb81db49066eaa7eaa6f10deff460cb0744bdce180ad1e3a1f3df"
    ),
    (RefineProfile.GENERAL, False): (
        "1b86b793c05c8491508ef17f0803f372e24d1d00efeb0a88234d91ad396b0946"
    ),
}


def _base_input_body(profile, structured_output, **extra):
    return build_chat_body(
        "alpha bravo charlie delta echo",
        model="test-model",
        words=5,
        keep_alive=900,
        structured_output=structured_output,
        profile=profile,
        **extra,
    )


@pytest.mark.parametrize("profile", list(RefineProfile))
@pytest.mark.parametrize("structured_output", [True, False])
def test_an_empty_vocabulary_keeps_the_base_body_byte_identical(profile, structured_output):
    expected = _BASE_BODY_SHA256[(profile, structured_output)]

    for body in (
        _base_input_body(profile, structured_output),
        _base_input_body(profile, structured_output, vocabulary=()),
    ):
        assert hashlib.sha256(encode(body)).hexdigest() == expected


@pytest.mark.parametrize("profile", list(RefineProfile))
def test_a_vocabulary_adds_one_instruction_naming_each_term(profile):
    plain = build_messages("alpha bravo", structured_output=True, profile=profile)
    with_terms = build_messages(
        "alpha bravo",
        structured_output=True,
        profile=profile,
        vocabulary=("Kubernetes", "PipeWire"),
    )

    added = [message for message in with_terms if message not in plain]
    assert len(with_terms) == len(plain) + 1
    assert len(added) == 1
    instruction = added[0]
    assert instruction["role"] == "system"
    assert "Kubernetes" in instruction["content"]
    assert "PipeWire" in instruction["content"]
    assert "exactly as written" in instruction["content"]
    # The benchmark system prompt is untouched and still leads.
    assert with_terms[0] == plain[0]
    assert with_terms[-1] == {"role": "user", "content": "alpha bravo"}
