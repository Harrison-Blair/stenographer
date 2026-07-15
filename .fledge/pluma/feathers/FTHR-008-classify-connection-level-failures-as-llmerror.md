---
id: FTHR-008
title: Classify connection-level failures as LlmError
plumage: PLM-003
status: pipping
priority: P0
depends_on: []
authored: 2026-07-15T05:19:36Z
agent: fledge-orchestrate/planning
fledge_version: 0.4.0
---

# FTHR-008: Classify connection-level failures as LlmError

## Description
`rewrite_prompt` (llm.py) currently classifies `urllib.error.HTTPError`, `urllib.error.URLError`, and `TimeoutError` into `LlmError`, but a failure while sending the request or reading the response body at the socket/connection level (e.g. `ConnectionResetError`, `http.client.IncompleteRead` — the local LLM server crashing or OOMing mid-response) is not caught by any of those and propagates as a raw exception. Because `Session._process` only catches `LlmError`, and nothing wraps the session-processor thread's run loop (`_process_utterance_queue`), that raw exception kills the thread outright — the daemon stays alive but silently stops processing all dictation (prompt and normal) until restart. This feather widens `rewrite_prompt`'s exception handling so every realistic failure mode of the local LLM HTTP call is classified into `LlmError`, which the existing `_process` catch already handles correctly (failure notification, error cue, raw-transcript fallback — untouched, no session.py change needed). Satisfies PLM-003 FC-1 (and, as a consequence requiring no additional code, FC-2).

## Affected Modules
Per `.fledge/nest/architecture.md` (cross-cutting `errors.py` policy) and `.fledge/nest/entry-points.md` (Session constructor boundary — `_process_utterance_queue` is the session-processor thread's run loop):
- `src/stenographer/llm.py` — `rewrite_prompt`'s exception handling, widened.
- `tests/test_llm.py` — new unit tests for the newly-classified failure modes (mocked `urllib.request.urlopen`, matching existing file conventions).
- `tests/test_session.py` — one new test proving the session-processor thread survives and keeps processing after this class of failure (uses the existing `_fake_llm_module`/`_process_prompt` and direct-queue-plus-`_process_utterance_queue()` test patterns already in this file).

## Approach
- In `rewrite_prompt`, add exception handling for connection/transport-level failures during `urlopen(...)`/`resp.read()` — at minimum `ConnectionError` (the builtin base class covering `ConnectionResetError`, `ConnectionAbortedError`, `BrokenPipeError`, etc.) and `http.client.IncompleteRead`. Catch these alongside the existing `except urllib.error.URLError` / `except TimeoutError` blocks (same `try` statement, same pattern: log at ERROR, `raise LlmError(...) from exc`), matching the existing per-exception-type message style (`f"llm: ... calling {url}: {exc}"` or similar, consistent with the other branches).
- No change to the success path, JSON-parsing, or content-extraction logic.
- No change to `session.py` — the existing `except llm_module.LlmError` in `_process` already handles the now-widened `LlmError` correctly (this is PLM-003 FC-2, satisfied as a consequence of this feather with no additional code).
- No retry logic (out of scope per PLM-003).

## Tests
`tests/test_llm.py` (new tests, following the existing `_cfg()`/`_response()` mocking helpers in that file):
- `test_rewrite_prompt_connection_reset_raises_llm_error` — mocked `urlopen` raising `ConnectionResetError` (or another `ConnectionError` subclass) during the call raises `LlmError`, not the raw exception.
- `test_rewrite_prompt_incomplete_read_raises_llm_error` — mocked `resp.read()` raising `http.client.IncompleteRead` raises `LlmError`, not the raw exception.

`tests/test_session.py` (new test, using the file's existing `_fake_llm_module`/queue-plus-`_process_utterance_queue()` patterns):
- `test_session_processor_survives_llm_connection_failure` — enqueues two prompt-mode utterances directly on `session._utterance_queue` (matching the 4/5-tuple shape used elsewhere in this file), the first configured (via a `_fake_llm_module` variant raising a `ConnectionResetError`-turned-`LlmError`) to fail, the second succeeding normally; enqueues `None` to terminate the loop; calls `session._process_utterance_queue()` directly (the established synchronous-test pattern, e.g. `test_processor_drops_cancelled_live_item`); asserts the second utterance was still fully processed (e.g. `injector.type_text`/`clipboard.copy` called for its text) — proving the thread loop did not die on the first utterance's failure.

Implementation order: write all three tests above, run against the unchanged code and confirm they FAIL for the expected reason (the two `test_llm.py` tests fail with the raw exception propagating instead of `LlmError`; the `test_session.py` test fails because the raw exception either propagates out of the test call or the second utterance is never processed), then implement the `llm.py` change until all three pass.

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before implementation and pass after.
- [x] AC-2: `rewrite_prompt` raises `LlmError` (never a raw `ConnectionError`/`http.client.IncompleteRead`) for connection-level failures during the HTTP call or response read (satisfies PLM-003 FC-1).
- [x] AC-3: A prompt-mode utterance whose LLM call fails with a connection-level error does not kill the session-processor thread; a subsequent utterance in the queue is still processed (satisfies PLM-003 FC-2).
- [x] AC-4: `.venv/bin/pytest -m "not integration"` passes with no regressions.
