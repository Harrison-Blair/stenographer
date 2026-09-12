# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the one Ollama chat request the refine stage makes. PURE: no I/O.

Separated from the refiner so the whole wire body can be asserted in a unit
test without a server, and so swapping a benchmark constant in
:mod:`stenographer.lib.refine.prompt` cannot silently change request *shape*.

``stream`` is false because the stage needs the whole reply before the output
guard can accept it, and ``temperature`` is zero because this is an edit, not a
generation.

``think`` is false unconditionally, and that is load-bearing rather than
tidiness: the benchmark measured a 2.1 s utterance become 8.5 s with thinking
on, and one model spent its entire token budget deliberating and returned an
empty answer. It is sent even to models that cannot think, which accept the
field without complaint.
"""

from __future__ import annotations

import json

from stenographer.lib.refine.prompt import (
    FEW_SHOT_EXAMPLES,
    NUM_PREDICT_BASE,
    NUM_PREDICT_MAX,
    NUM_PREDICT_PER_WORD,
    RESPONSE_KEY,
    RESPONSE_SCHEMA,
    SYSTEM_PROMPT,
)

USER_AGENT = "stenographer-refine"


def num_predict_for(words: int) -> int:
    """Cap the reply length relative to the input; cleanup never expands much.

    Scales with the utterance and then stops: a long dictation still needs a
    bounded worst case, since a model that starts looping otherwise spends the
    whole time budget doing it.
    """

    return min(NUM_PREDICT_MAX, NUM_PREDICT_BASE + NUM_PREDICT_PER_WORD * max(0, words))


def _assistant_turn(cleaned: str, *, structured_output: bool) -> str:
    """Render an example answer in whatever format the live reply will use."""

    if not structured_output:
        return cleaned
    return json.dumps({RESPONSE_KEY: cleaned}, ensure_ascii=False)


def build_messages(text: str, *, structured_output: bool) -> list[dict[str, str]]:
    """The system turn, the few-shot turns, and the utterance to clean."""

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for spoken, cleaned in FEW_SHOT_EXAMPLES:
        messages.append({"role": "user", "content": spoken})
        answer = _assistant_turn(cleaned, structured_output=structured_output)
        messages.append({"role": "assistant", "content": answer})
    messages.append({"role": "user", "content": text})
    return messages


def build_chat_body(
    text: str,
    *,
    model: str,
    words: int,
    keep_alive: int,
    structured_output: bool,
) -> dict[str, object]:
    """The complete ``/api/chat`` body for one utterance."""

    body: dict[str, object] = {
        "model": model,
        "messages": build_messages(text, structured_output=structured_output),
        "stream": False,
        "think": False,
        "keep_alive": keep_alive,
        "options": {"temperature": 0, "num_predict": num_predict_for(words)},
    }
    if structured_output:
        body["format"] = RESPONSE_SCHEMA
    return body


def build_warm_body(*, model: str, keep_alive: int) -> dict[str, object]:
    """A no-token ``/api/generate`` that only resides the model in memory."""

    return {
        "model": model,
        "prompt": "",
        "stream": False,
        "think": False,
        "keep_alive": keep_alive,
        "options": {"num_predict": 0},
    }


def build_unload_body(*, model: str) -> dict[str, object]:
    """``keep_alive = 0`` asks Ollama to release the model immediately."""

    return {"model": model, "prompt": "", "stream": False, "keep_alive": 0}


def encode(body: dict[str, object]) -> bytes:
    """Serialize a request body exactly as it goes on the wire."""

    return json.dumps(body).encode("utf-8")
