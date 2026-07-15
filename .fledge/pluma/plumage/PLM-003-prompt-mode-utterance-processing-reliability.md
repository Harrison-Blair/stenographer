---
id: PLM-003
title: Prompt-mode utterance-processing reliability
status: fledged
priority: P0
authored: 2026-07-15T04:53:54Z
agent: fledge-orchestrate/planning
fledge_version: 0.4.0
---

# PLM-003: Prompt-mode utterance-processing reliability

## Context
PLM-002 added a second, LLM-rewriting dictation mode ("prompt mode"). A code review of the current `dev` branch found three correctness bugs in that mode's utterance-processing path, all rooted in `Session._process` (session.py) and its supporting `_on_model_loaded` callback and `llm.py`'s `rewrite_prompt`:

1. `rewrite_prompt` only classifies `HTTPError`/`URLError`/`TimeoutError` into `LlmError`. A connection-level failure while reading the response body (e.g. the local LLM server crashing or OOMing mid-response — `ConnectionResetError`, `http.client.IncompleteRead`) escapes uncaught. `_process` only catches `LlmError`, and nothing wraps the session-processor thread's run loop, so this exception kills that thread outright — the daemon keeps running but silently stops processing **all** dictation, prompt mode and normal mode alike, until restart.
2. Under lazy ASR mode, a prompt-mode recording whose first utterance triggers the (one-time) model load gets the wrong "Listening…" notification once loading finishes — the plain-mode notification fires instead of the prompt-mode one, so the prompt indicator never appears for that utterance.
3. On an LLM rewrite failure, the failure notification and `error` cue play as designed (per PLM-002 FC-4/FC-5, the raw transcript is still typed/copied as a fallback — this part is intentional and unchanged) — but the code then also plays the `transcribe_done` success cue at the end of the same utterance, so the user hears a contradictory error-then-success cue sequence for one failed rewrite.

This plumage fixes all three so prompt mode's failure and lazy-load paths behave as PLM-002 originally intended.

## User Stories
- As a user of either dictation mode, I want a local LLM server crash mid-response to fail just that one utterance (with the existing failure notification/cue and raw-transcript fallback) rather than silently killing all future dictation until I restart the daemon.
- As a user with lazy ASR model loading enabled, I want the prompt-mode "Listening (prompt)…" notification to appear correctly even when my first prompt-mode utterance is the one that triggers the model load.
- As a user whose LLM rewrite fails, I want to hear only the failure cue for that utterance (not a failure cue followed by a success cue), while still getting my raw transcript typed/copied as today.

## Functional Criteria
1. FC-1: `rewrite_prompt` (llm.py) classifies connection-level failures while sending the request or reading the response (including but not limited to `ConnectionError` and `http.client.IncompleteRead`) as `LlmError`, the same as the HTTP/URL/timeout failures it already classifies.
2. FC-2: An `LlmError` raised during prompt-mode processing never propagates out of the session-processor thread's run loop; that thread keeps processing subsequent utterances (prompt and normal) after any single utterance's LLM failure.
3. FC-3: In `_on_model_loaded`, when the recording still in progress is prompt-mode, the prompt-mode "Listening (prompt)…" notification is shown (not the plain-mode one) once lazy model loading completes.
4. FC-4: On an LLM rewrite failure in prompt mode, exactly one cue plays for that utterance — `error` — and the existing `transcribe_done` success cue does not also play; the raw-transcript typed/clipboard fallback (PLM-002 FC-4) is unchanged.

## Acceptance Criteria
- [x] AC-1: A test demonstrates that `rewrite_prompt` raises `LlmError` (not a raw exception) when the underlying HTTP call raises a connection-level read failure (e.g. `http.client.IncompleteRead` or `ConnectionResetError`) partway through reading the response.
- [x] AC-2: A test demonstrates that when `_process` handles an `LlmError` for a prompt-mode utterance, the session-processor thread is still alive and able to process a subsequent utterance afterward (no thread death).
- [x] AC-3: A test demonstrates that a prompt-mode recording whose first utterance triggers lazy model loading shows the prompt-mode listening notification (not the plain one) once the model finishes loading while still recording.
- [x] AC-4: A test demonstrates that on an LLM rewrite failure in prompt mode, the `error` cue plays, the `transcribe_done` cue does not play, and the raw transcript is still typed and copied to the clipboard.
- [x] AC-5: The full unit test suite (`.venv/bin/pytest -m "not integration"`) passes with no regressions to existing dictation-mode or prompt-mode behavior.

## Out of Scope
- Retry/backoff logic for LLM calls.
- Tuning `llm.timeout_seconds` or any other `[stenographer.llm]` config defaults.
- A catch-all exception guard around the session-processor loop's run method (declined — the fix is scoped to correctly classifying LLM-related exceptions in llm.py, not general thread-death defense-in-depth).
- Prompt-mode streaming (prompt mode never streams; unaffected).
- Any change to non-prompt (`dictate`-source) processing behavior.

## Open Questions
None — resolved during interrogation: LlmError classification widened in llm.py only (no session.py catch-all); LLM-failure fallback stays raw-transcript-typed (per PLM-002 FC-4) with the fix being suppression of the contradictory success cue, not an early return with no output; `_on_model_loaded` branches on `_recording_source` exactly like `on_recording_start` already does; priority P0.
