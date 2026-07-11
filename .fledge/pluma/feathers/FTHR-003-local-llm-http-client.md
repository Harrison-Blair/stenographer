---
id: FTHR-003
title: Local LLM HTTP client
plumage: PLM-002
status: egg
priority: P1
depends_on: [FTHR-002]
authored: 2026-07-11T05:52:43Z
agent: fledge-orchestrate/planning
fledge_version: 0.4.0
---

# FTHR-003: Local LLM HTTP client

## Description
A new, self-contained module that sends a transcript to a locally-running, OpenAI-compatible chat-completions HTTP endpoint (per `LlmConfig` from FTHR-002) with the configured system prompt, and returns the rewritten text. On any failure (unreachable, timeout, non-2xx status, malformed/empty response body), it raises a new `LlmError` rather than returning a partial/garbage result, so callers can implement the fallback-to-raw-transcript policy (PLM-002 FC-4) without inspecting response internals themselves. This feather has no dependency on `Session`, the hotkey layer, or notifications — it is tested entirely in isolation with a mocked HTTP layer. Satisfies PLM-002 FC-2 (the LLM-call mechanism) and half of FC-4 (raising a typed, catchable failure signal).

## Affected Modules
Per `.fledge/nest/dependencies.md` (no existing HTTP client dependency — stdlib only, per the interrogated decision) and `.fledge/nest/architecture.md` (cross-cutting `errors.py` policy: components raise `StenographerError` subclasses):
- `src/stenographer/llm.py` (new file) — the HTTP client function.
- `src/stenographer/errors.py` — add `LlmError(StenographerError)`, following the existing subclass style (e.g. `TranscriptionError`, `UpdateError`) with a one-line docstring.
- `tests/test_llm.py` (new file) — unit tests with mocked `urllib.request.urlopen`.

## Approach
- Public function: `rewrite_prompt(cfg: LlmConfig, transcript: str) -> str` in the new `stenographer/llm.py`. This is the interface contract FTHR-004 (session routing) is written against — its signature and module path must not change without updating that feather too.
- Build a JSON request body per the OpenAI chat-completions shape: `{"model": cfg.model, "messages": [{"role": "system", "content": cfg.system_prompt}, {"role": "user", "content": transcript}], "temperature": cfg.temperature, "max_tokens": cfg.max_tokens}`. POST to `f"{cfg.base_url}/v1/chat/completions"` via `urllib.request.Request`/`urlopen` (mirrors the stdlib HTTPS pattern already used in `update.py` for GitHub API calls), with `timeout=cfg.timeout_seconds`.
- On success, parse the JSON response and extract `response["choices"][0]["message"]["content"]`; strip surrounding whitespace; if the result is empty or any expected key is missing, raise `LlmError`.
- On `urllib.error.URLError` (covers connection refused/DNS failure), `TimeoutError`/`socket.timeout`, `urllib.error.HTTPError` (non-2xx), or `json.JSONDecodeError`, catch and re-raise as `LlmError` with a message identifying the failure kind (mirrors `output/inject.py`'s pattern of catching a specific exception tuple and logging before returning/raising a uniform failure signal).
- Log at ERROR on failure (`notify_failure`-style, per `errors.py` convention), at DEBUG on the outbound request (mirroring existing per-file `logger = logging.getLogger(__name__)` + context-marker style, e.g. `"llm: ..."`).
- No retry logic (explicitly out of scope per PLM-002).

## Tests
All in `tests/test_llm.py`, mocking `urllib.request.urlopen` (`unittest.mock.patch`) rather than making real network calls:
- `test_rewrite_prompt_success_returns_content` — a mocked 200 response with a valid choices/message/content body returns the extracted, stripped text.
- `test_rewrite_prompt_sends_expected_request_body` — asserts the POSTed JSON body contains `model`, the system + user messages (system = `cfg.system_prompt`, user = the transcript), `temperature`, and `max_tokens` matching the passed `LlmConfig`.
- `test_rewrite_prompt_connection_error_raises_llm_error` — mocked `urllib.error.URLError` raises `LlmError`.
- `test_rewrite_prompt_timeout_raises_llm_error` — mocked timeout raises `LlmError`.
- `test_rewrite_prompt_http_error_raises_llm_error` — mocked `urllib.error.HTTPError` (e.g. 500) raises `LlmError`.
- `test_rewrite_prompt_malformed_json_raises_llm_error` — a response body that isn't valid JSON raises `LlmError`.
- `test_rewrite_prompt_missing_content_key_raises_llm_error` — valid JSON missing the expected `choices`/`message`/`content` path raises `LlmError`.
- `test_rewrite_prompt_empty_content_raises_llm_error` — a response whose `content` is `""` (or whitespace-only) raises `LlmError`.

Implementation order: write all tests above, run against the unchanged/nonexistent module and confirm they fail for the expected reason (`ModuleNotFoundError`/`ImportError`), then implement `llm.py` until all pass.

## Acceptance Criteria
- [ ] AC-1: The tests listed above were observed failing before implementation and pass after.
- [ ] AC-2: `rewrite_prompt()` sends a spec-conformant OpenAI-compatible chat-completions request built from `LlmConfig` and the transcript (satisfies PLM-002 FC-2).
- [ ] AC-3: Every failure mode (unreachable, timeout, non-2xx, malformed/empty response) raises `LlmError` rather than returning a partial result or propagating a raw stdlib exception (satisfies half of PLM-002 FC-4).
- [ ] AC-4: `.venv/bin/pytest -m "not integration"` passes with no regressions; no real network access occurs during the test run.
