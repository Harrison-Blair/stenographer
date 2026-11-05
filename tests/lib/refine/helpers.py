# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared helpers for refine tests."""

import json

import pytest

from stenographer.lib.config.models import Config
from stenographer.lib.refine import ollama_refiner
from stenographer.lib.refine.client import installed_model_names
from stenographer.lib.refine.ollama_refiner import OllamaRefiner
from stenographer.lib.refine.prompt import RESPONSE_KEY

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

    def warm_model(host, model, *, keep_alive, timeout=None):
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


@pytest.fixture
def installed_refiner() -> OllamaRefiner:
    section = Config.defaults().refine
    installed = installed_model_names(section.host)
    if not installed:
        pytest.skip(f"no Ollama answered at {section.host}")
    if section.model not in installed:
        pytest.skip(f"{section.model} is not installed; this suite never pulls models")
    built = OllamaRefiner(
        host=section.host,
        model=section.model,
        min_words=section.min_words,
        structured_output=section.structured_output,
        keep_alive=Config.defaults().asr.idle_unload_seconds,
    )
    if not built.warm():
        pytest.skip(f"{section.model} could not be loaded on {section.host}")
    return built
