# SPDX-License-Identifier: GPL-3.0-or-later
"""The refiner's fail-open contract, and what it records about each attempt.

``post_chat``, ``is_model_loaded`` and ``warm_model`` are the only seams
replaced here — the module boundary the package itself already draws around
``urllib`` — so the request builder, the parser, the guard, the classification,
and the measurement all run for real. Nothing starts a server and nothing
touches the network.
"""

from __future__ import annotations

import dataclasses
import json
import logging

import pytest

from stenographer.lib.config.models import Config, RefineConfig
from stenographer.lib.refine import ollama_refiner
from stenographer.lib.refine.errors import RefineTimeoutError, RefineTransportError
from stenographer.lib.refine.factory import build_refiner
from stenographer.lib.refine.null_refiner import NullRefiner
from stenographer.lib.refine.ollama_refiner import OllamaRefiner
from stenographer.lib.refine.prompt import RESPONSE_KEY
from stenographer.lib.refine.results import (
    OUTCOME_APPLIED,
    OUTCOME_FAILED,
    OUTCOME_REJECTED,
    OUTCOME_SKIPPED,
    OUTCOME_TIMEOUT,
)

SPOKEN = "um i think we should ship it on thursday no wait friday okay "
CLEANED = "I think we should ship it on Friday. "


def _refiner(**overrides) -> OllamaRefiner:
    kwargs = {
        "host": "http://127.0.0.1:11434",
        "model": "test-model",
        "min_words": 10,
        "structured_output": True,
        "keep_alive": 900,
    }
    kwargs.update(overrides)
    return OllamaRefiner(**kwargs)


def _answer(text: str, *, structured: bool = True) -> bytes:
    content = json.dumps({RESPONSE_KEY: text}) if structured else text
    return json.dumps({"message": {"content": content}}).encode()


@pytest.fixture
def transport(monkeypatch):
    """Replace the one function that opens a socket, and capture its calls."""

    calls: list[dict] = []
    warm_calls: list[dict] = []
    state: dict = {
        "reply": _answer(CLEANED),
        "raise": None,
        "loaded": True,
        "warm_raise": None,
    }

    def post_chat(host, body, *, timeout):
        calls.append({"host": host, "body": body, "timeout": timeout})
        if state["raise"] is not None:
            raise state["raise"]
        return state["reply"]

    def is_model_loaded(host, model):
        return state["loaded"]

    def warm_model(host, model, *, keep_alive, timeout):
        warm_calls.append(
            {"host": host, "model": model, "keep_alive": keep_alive, "timeout": timeout}
        )
        if state["warm_raise"] is not None:
            raise state["warm_raise"]

    monkeypatch.setattr(ollama_refiner, "post_chat", post_chat)
    monkeypatch.setattr(ollama_refiner, "is_model_loaded", is_model_loaded)
    monkeypatch.setattr(ollama_refiner, "warm_model", warm_model)
    state["calls"] = calls
    state["warm_calls"] = warm_calls
    return state


def test_a_clean_reply_is_delivered_and_measured(transport):
    refiner = _refiner()

    assert refiner.refine(SPOKEN) == CLEANED

    result = refiner.last_result
    assert result.outcome == OUTCOME_APPLIED
    assert result.applied is True and result.failed is False and result.attempted is True
    assert result.chars_in == len(SPOKEN)
    assert result.chars_out == len(CLEANED)
    assert result.duration_ms is not None and result.duration_ms >= 0


def test_the_time_budget_sent_follows_the_word_count(transport):
    from stenographer.lib.refine.policy import timeout_seconds, word_count

    _refiner().refine(SPOKEN)

    assert transport["calls"][0]["timeout"] == pytest.approx(timeout_seconds(word_count(SPOKEN)))


def test_a_resident_model_is_not_loaded_again(transport):
    _refiner().refine(SPOKEN)

    assert transport["warm_calls"] == []
    assert len(transport["calls"]) == 1


def test_a_cold_model_is_loaded_on_its_own_budget_before_the_utterance_is_timed(transport):
    """The utterance budget assumes a warm model. A cold load must get the
    long budget first, and only then is the ordinary one started."""
    from stenographer.lib.refine.policy import (
        COLD_LOAD_TIMEOUT_SECONDS,
        timeout_seconds,
        word_count,
    )

    transport["loaded"] = False
    refiner = _refiner(keep_alive=-1)

    assert refiner.refine(SPOKEN) == CLEANED
    assert refiner.last_result.outcome == OUTCOME_APPLIED

    (warm,) = transport["warm_calls"]
    assert warm["model"] == "test-model"
    assert warm["keep_alive"] == -1
    assert warm["timeout"] == pytest.approx(COLD_LOAD_TIMEOUT_SECONDS)
    (chat,) = transport["calls"]
    assert chat["timeout"] == pytest.approx(timeout_seconds(word_count(SPOKEN)))


@pytest.mark.parametrize(
    ("failure", "outcome"),
    [
        (RefineTimeoutError("ollama did not answer in time"), OUTCOME_TIMEOUT),
        (RefineTransportError("ollama could not be reached"), OUTCOME_FAILED),
    ],
)
def test_a_load_that_does_not_finish_delivers_the_raw_text_without_a_chat(
    transport, failure, outcome
):
    transport["loaded"] = False
    transport["warm_raise"] = failure
    refiner = _refiner()

    assert refiner.refine(SPOKEN) == SPOKEN
    assert refiner.last_result.outcome == outcome
    assert refiner.last_result.failed is True
    assert transport["calls"] == []


def test_short_text_never_reaches_the_model(transport):
    refiner = _refiner()
    short = "just five words here now "

    assert refiner.will_refine(short) is False
    assert refiner.refine(short) == short
    assert transport["calls"] == []
    assert refiner.last_result.outcome == OUTCOME_SKIPPED
    assert refiner.last_result.attempted is False


@pytest.mark.parametrize(
    ("failure", "outcome"),
    [
        (RefineTimeoutError("ollama did not answer in time"), OUTCOME_TIMEOUT),
        (RefineTransportError("ollama could not be reached"), OUTCOME_FAILED),
        (RuntimeError("something unexpected"), OUTCOME_FAILED),
    ],
)
def test_every_failure_delivers_the_raw_text_and_is_classified(transport, failure, outcome):
    transport["raise"] = failure
    refiner = _refiner()

    assert refiner.refine(SPOKEN) == SPOKEN
    assert refiner.last_result.outcome == outcome
    assert refiner.last_result.failed is True
    assert refiner.last_result.chars_out is None


def test_a_reply_the_guard_refuses_delivers_the_raw_text(transport):
    transport["reply"] = _answer("Friday.")

    refiner = _refiner()

    assert refiner.refine(SPOKEN) == SPOKEN
    assert refiner.last_result.outcome == OUTCOME_REJECTED


def test_a_malformed_reply_delivers_the_raw_text(transport):
    transport["reply"] = b"<html>proxy error</html>"

    assert _refiner().refine(SPOKEN) == SPOKEN


def test_no_transcript_or_reply_text_ever_reaches_the_log(transport, caplog):
    transport["reply"] = _answer(f"{SPOKEN} {SPOKEN} {SPOKEN} {SPOKEN}")

    with caplog.at_level(logging.DEBUG, logger="stenographer.lib.refine"):
        assert _refiner().refine(SPOKEN) == SPOKEN

    text = "\n".join(caplog.messages)
    assert "refine: not_applied" in text
    assert "thursday" not in text and "friday" not in text.casefold()


def test_plain_text_replies_work_without_the_schema(transport):
    transport["reply"] = _answer(CLEANED, structured=False)

    assert _refiner(structured_output=False).refine(SPOKEN) == CLEANED


def test_the_disabled_stage_is_an_object_not_a_special_case():
    refiner = NullRefiner()

    assert refiner.will_refine("anything at all, however long it happens to be") is False
    assert refiner.refine(SPOKEN) == SPOKEN
    assert refiner.last_result is None


@pytest.mark.parametrize(
    "section",
    [
        RefineConfig(enabled=False),
        RefineConfig(enabled=True, model="   "),
        RefineConfig(enabled=True, host=""),
    ],
)
def test_the_factory_builds_nothing_that_can_reach_the_network(section):
    assert isinstance(build_refiner(section, idle_unload_seconds=900), NullRefiner)


def test_the_factory_carries_the_asr_idle_window_into_keep_alive():
    refiner = build_refiner(RefineConfig(enabled=True), idle_unload_seconds=0)

    assert isinstance(refiner, OllamaRefiner)
    assert refiner.keep_alive == -1
    assert build_refiner(RefineConfig(enabled=True), idle_unload_seconds=60).keep_alive == 60


def test_an_explicit_opt_in_does_not_need_the_daemon_setting():
    """``transcribe --refine`` must work against a config with the stage off."""
    section = Config.defaults().refine

    assert section.enabled is False
    assert isinstance(build_refiner(section, idle_unload_seconds=900), NullRefiner)
    assert isinstance(build_refiner(section, idle_unload_seconds=900, enabled=True), OllamaRefiner)


def test_an_explicit_opt_out_overrides_an_enabled_config():
    section = dataclasses.replace(Config.defaults().refine, enabled=True)

    assert isinstance(build_refiner(section, idle_unload_seconds=900, enabled=False), NullRefiner)
