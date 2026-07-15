# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import http.client
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from stenographer.config import LlmConfig
from stenographer.errors import LlmError
from stenographer.llm import rewrite_prompt


def _cfg(**overrides) -> LlmConfig:
    defaults = dict(
        base_url="http://localhost:11434",
        model="test-model",
        system_prompt="Rewrite the following transcript.",
        timeout_seconds=5.0,
        temperature=0.2,
        max_tokens=512,
    )
    defaults.update(overrides)
    return LlmConfig(**defaults)


def _response(body: dict | bytes) -> MagicMock:
    """Build a mock urlopen() context-manager result."""
    raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = raw
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def test_rewrite_prompt_success_returns_content():
    body = {"choices": [{"message": {"content": "  Rewritten text.  "}}]}
    with patch("stenographer.llm.urllib.request.urlopen", return_value=_response(body)):
        result = rewrite_prompt(_cfg(), "raw transcript")
    assert result == "Rewritten text."


def test_rewrite_prompt_sends_expected_request_body():
    body = {"choices": [{"message": {"content": "ok"}}]}
    cfg = _cfg(model="llama-3", temperature=0.7, max_tokens=256)
    with patch(
        "stenographer.llm.urllib.request.urlopen", return_value=_response(body)
    ) as mock_urlopen:
        rewrite_prompt(cfg, "hello world")

    request = mock_urlopen.call_args[0][0]
    sent = json.loads(request.data.decode("utf-8"))
    assert sent["model"] == "llama-3"
    assert sent["messages"] == [
        {"role": "system", "content": cfg.system_prompt},
        {"role": "user", "content": "hello world"},
    ]
    assert sent["temperature"] == 0.7
    assert sent["max_tokens"] == 256


def test_rewrite_prompt_connection_error_raises_llm_error():
    with (
        patch(
            "stenographer.llm.urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ),
        pytest.raises(LlmError),
    ):
        rewrite_prompt(_cfg(), "raw transcript")


def test_rewrite_prompt_timeout_raises_llm_error():
    with (
        patch(
            "stenographer.llm.urllib.request.urlopen",
            side_effect=TimeoutError("timed out"),
        ),
        pytest.raises(LlmError),
    ):
        rewrite_prompt(_cfg(), "raw transcript")


def test_rewrite_prompt_http_error_raises_llm_error():
    err = urllib.error.HTTPError(
        url="http://localhost:11434/v1/chat/completions",
        code=500,
        msg="Internal Server Error",
        hdrs=None,
        fp=None,
    )
    with (
        patch("stenographer.llm.urllib.request.urlopen", side_effect=err),
        pytest.raises(LlmError),
    ):
        rewrite_prompt(_cfg(), "raw transcript")


def test_rewrite_prompt_connection_reset_raises_llm_error():
    with (
        patch(
            "stenographer.llm.urllib.request.urlopen",
            side_effect=ConnectionResetError("connection reset by peer"),
        ),
        pytest.raises(LlmError),
    ):
        rewrite_prompt(_cfg(), "raw transcript")


def test_rewrite_prompt_incomplete_read_raises_llm_error():
    resp = MagicMock()
    resp.read.side_effect = http.client.IncompleteRead(b"partial")
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    with (
        patch("stenographer.llm.urllib.request.urlopen", return_value=resp),
        pytest.raises(LlmError),
    ):
        rewrite_prompt(_cfg(), "raw transcript")


def test_rewrite_prompt_malformed_json_raises_llm_error():
    with (
        patch(
            "stenographer.llm.urllib.request.urlopen",
            return_value=_response(b"not valid json"),
        ),
        pytest.raises(LlmError),
    ):
        rewrite_prompt(_cfg(), "raw transcript")


def test_rewrite_prompt_missing_content_key_raises_llm_error():
    body = {"choices": [{"message": {}}]}
    with (
        patch("stenographer.llm.urllib.request.urlopen", return_value=_response(body)),
        pytest.raises(LlmError),
    ):
        rewrite_prompt(_cfg(), "raw transcript")


def test_rewrite_prompt_empty_content_raises_llm_error():
    body = {"choices": [{"message": {"content": "   "}}]}
    with (
        patch("stenographer.llm.urllib.request.urlopen", return_value=_response(body)),
        pytest.raises(LlmError),
    ):
        rewrite_prompt(_cfg(), "raw transcript")
