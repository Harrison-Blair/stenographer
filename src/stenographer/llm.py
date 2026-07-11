# SPDX-License-Identifier: GPL-3.0-or-later
"""Local LLM HTTP client.

Sends a transcript to a locally-running, OpenAI-compatible
chat-completions endpoint and returns the rewritten text. This module
has no dependency on ``Session`` or the hotkey layer; every failure
mode is collapsed into :class:`LlmError` so callers can implement a
fallback-to-raw-transcript policy without inspecting response
internals.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

from stenographer.errors import LlmError

if TYPE_CHECKING:
    from stenographer.config import LlmConfig

logger = logging.getLogger(__name__)


def rewrite_prompt(cfg: LlmConfig, transcript: str) -> str:
    """Send ``transcript`` to the configured LLM endpoint and return the rewrite.

    Raises :class:`LlmError` on any failure: unreachable endpoint,
    timeout, non-2xx status, or a malformed/empty response body.
    """
    url = f"{cfg.base_url}/v1/chat/completions"
    payload = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": cfg.system_prompt},
            {"role": "user", "content": transcript},
        ],
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    logger.debug("llm: requesting rewrite from %s (model=%s)", url, cfg.model)
    try:
        with urllib.request.urlopen(request, timeout=cfg.timeout_seconds) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        logger.error("llm: HTTP %s from %s", exc.code, url)
        raise LlmError(f"llm: HTTP {exc.code} from {url}") from exc
    except urllib.error.URLError as exc:
        logger.error("llm: network error calling %s: %s", url, exc.reason)
        raise LlmError(f"llm: network error calling {url}: {exc.reason}") from exc
    except TimeoutError as exc:
        logger.error("llm: timed out calling %s", url)
        raise LlmError(f"llm: timed out calling {url}") from exc

    try:
        response = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("llm: malformed JSON response from %s", url)
        raise LlmError(f"llm: malformed JSON response from {url}") from exc

    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        logger.error("llm: response from %s missing expected content path", url)
        raise LlmError(f"llm: response from {url} missing expected content path") from exc

    content = content.strip() if isinstance(content, str) else ""
    if not content:
        logger.error("llm: response from %s had empty content", url)
        raise LlmError(f"llm: response from {url} had empty content")

    return content
