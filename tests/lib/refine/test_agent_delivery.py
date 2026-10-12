# SPDX-License-Identifier: GPL-3.0-or-later
"""Untrusted replies traverse production parsing and Agent fail-open delivery."""

from __future__ import annotations

import json
import logging

import pytest

from stenographer.lib.refine.errors import (
    RefineRejectedError,
    RefineResponseError,
    RefineTransportError,
)
from stenographer.lib.refine.profiles import RefineProfile
from stenographer.lib.refine.prompt import RESPONSE_KEY
from stenographer.lib.refine.response import refined_text
from stenographer.lib.refine.results import OUTCOME_APPLIED, OUTCOME_FAILED, OUTCOME_REJECTED
from tests.lib.refine.test_refiner import _answer, _refiner
from tests.lib.refine.test_refiner import transport as production_transport

transport = production_transport
SPOKEN = "The request was rejected by the server because the credentials had expired. "
EDITED = "The server rejected the request because the credentials expired."


@pytest.mark.parametrize("structured", [True, False])
@pytest.mark.parametrize(
    ("spoken", "candidate"),
    [
        ("Maybe the cache failed. ", "Possibly the cache failed."),
        ("Maybe the cache failed. ", "A cache failure is possible."),
        ("Ask Codex to review 30 requests. ", "Ask Gemini to review 40 requests."),
        ("Do not change the timeout. ", "Change the timeout."),
        ("Only investigate until I approve. ", "Implement and deploy now."),
        ("Review the log. ", "Detailed findings. " * 100),
        ("Review the logs and report findings. " * 100, "Done."),
    ],
)
def test_agent_trusts_model_meaning_and_length_in_production(
    transport, structured, spoken, candidate
):
    transport["reply"] = _answer(candidate, structured=structured)
    refiner = _refiner(min_words=1, structured_output=structured)
    assert refiner.refine(spoken, profile=RefineProfile.AGENT) == candidate.rstrip() + " "
    assert refiner.last_result.outcome == OUTCOME_APPLIED


@pytest.mark.parametrize("structured", [True, False])
def test_substantial_agent_reply_uses_production_delivery_and_restores_space(transport, structured):
    transport["reply"] = _answer(EDITED, structured=structured)
    refiner = _refiner(structured_output=structured)
    assert refiner.refine(SPOKEN, profile=RefineProfile.AGENT) == EDITED + " "
    assert refiner.last_result.outcome == OUTCOME_APPLIED


@pytest.mark.parametrize("structured", [True, False])
def test_rejected_agent_reply_falls_back_without_logging_dictation(transport, caplog, structured):
    spoken = "Only investigate private_job.py and do not change it. "
    candidate = '```\n"private_job.py"\n```'
    transport["reply"] = _answer(candidate, structured=structured)
    refiner = _refiner(min_words=1, structured_output=structured)
    with caplog.at_level(logging.DEBUG):
        assert refiner.refine(spoken, profile=RefineProfile.AGENT) == spoken
    assert refiner.last_result.outcome == OUTCOME_REJECTED
    assert "private_job" not in caplog.text
    assert candidate not in caplog.text
    assert spoken not in caplog.text


@pytest.mark.parametrize("structured", [True, False])
def test_cancellation_keeps_agent_reply_from_delivery(transport, structured):
    transport["reply"] = _answer(EDITED, structured=structured)
    refiner = _refiner(structured_output=structured)
    assert refiner.refine(SPOKEN, profile=RefineProfile.AGENT, cancelled=lambda: True) == SPOKEN
    assert transport["calls"] == []


@pytest.mark.parametrize("structured", [True, False])
@pytest.mark.parametrize("failure", ["transport", "parsing"])
def test_agent_technical_failures_preserve_transcript_privately(
    transport, caplog, structured, failure
):
    if failure == "transport":
        transport["raise"] = RefineTransportError("connection failed")
    else:
        transport["reply"] = b'{"message":{"content":null}}'
    refiner = _refiner(structured_output=structured)
    with caplog.at_level(logging.DEBUG):
        assert refiner.refine(SPOKEN, profile=RefineProfile.AGENT) == SPOKEN
    assert refiner.last_result.outcome == OUTCOME_FAILED
    assert SPOKEN not in caplog.text


@pytest.mark.parametrize("structured", [True, False])
@pytest.mark.parametrize("output", ["", " \n ", "\"'wrapped'\""])
def test_empty_and_double_wrapped_outputs_are_rejected(structured, output):
    with pytest.raises(RefineRejectedError):
        refined_text(
            _answer(output, structured=structured),
            SPOKEN,
            structured_output=structured,
            profile=RefineProfile.AGENT,
        )


@pytest.mark.parametrize("structured", [True, False])
def test_truncated_agent_reply_is_never_deliverable(structured):
    content = json.dumps({RESPONSE_KEY: EDITED}) if structured else EDITED
    payload = json.dumps({"done_reason": "length", "message": {"content": content}})
    with pytest.raises(RefineRejectedError, match="truncated"):
        refined_text(payload, SPOKEN, structured_output=structured, profile=RefineProfile.AGENT)


@pytest.mark.parametrize(
    "payload",
    ["not JSON", "null", "[]", "42", "{}", '{"message":null}', '{"message":{"content":[]}}'],
)
def test_wrong_response_shapes_have_private_fixed_errors(payload):
    with pytest.raises(RefineResponseError) as caught:
        refined_text(payload, SPOKEN, structured_output=True, profile=RefineProfile.AGENT)
    assert SPOKEN not in str(caught.value)


@pytest.mark.parametrize(
    "content", ["null", "[]", "42", "{}", '{"text":null}', '{"text":{"text":"nested"}}']
)
def test_wrong_structured_shapes_are_not_dictation(content):
    payload = json.dumps({"message": {"content": content}})
    with pytest.raises(RefineResponseError):
        refined_text(payload, SPOKEN, structured_output=True, profile=RefineProfile.AGENT)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "é # ? % & ; +\n__proto__ constructor toString "
        "hasOwnProperty prototype .. %2e%2e%2f /tmp/demo",
        "word " * 10000,
    ],
)
def test_arbitrary_user_text_is_data_in_the_request(text):
    from stenographer.lib.refine.request import build_messages

    messages = build_messages(text, structured_output=False, profile=RefineProfile.AGENT)
    assert messages[-1] == {"role": "user", "content": text}


@pytest.mark.parametrize("structured", [True, False])
@pytest.mark.parametrize(
    "wrapper", ['"{}"', "'{}'", "\u201c{}\u201d", "\u2018{}\u2019", "```text\n{}\n```"]
)
def test_one_wrapper_can_wrap_a_substantial_agent_rewrite(structured, wrapper):
    output = wrapper.format(EDITED)
    assert (
        refined_text(
            _answer(output, structured=structured),
            SPOKEN,
            structured_output=structured,
            profile=RefineProfile.AGENT,
        )
        == EDITED
    )
