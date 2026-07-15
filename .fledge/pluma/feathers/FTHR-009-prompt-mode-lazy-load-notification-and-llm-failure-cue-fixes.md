---
id: FTHR-009
title: Prompt-mode lazy-load notification and LLM-failure cue fixes
plumage: PLM-003
status: hatching
priority: P0
depends_on: []
authored: 2026-07-15T05:21:04Z
agent: fledge-orchestrate/planning
fledge_version: 0.4.0
---

# FTHR-009: Prompt-mode lazy-load notification and LLM-failure cue fixes

## Description
Two independent one-method-each bugs in `Session`'s prompt-mode utterance path, both in session.py:
- `_on_model_loaded` (the lazy-ASR model-load-complete callback) always shows the plain `Listening…` notification when still recording, ignoring `self._recording_source`. A prompt-mode recording whose first utterance triggers the lazy model load gets the wrong notification once loading finishes — the prompt indicator never appears for that utterance (F7).
- `_process`'s LLM-failure branch (`except llm_module.LlmError`) correctly shows the failure notification and plays the `error` cue, but doesn't suppress the function's final `transcribe_done` cue play — so on a failed rewrite the user hears `error` immediately followed by `transcribe_done`, even though the raw-transcript fallback output (typed/clipboarded) is correct and intentional per PLM-002 FC-4 (F8).

Satisfies PLM-003 FC-3 (notification) and FC-4 (single, correct cue on failure).

## Affected Modules
Per `.fledge/nest/entry-points.md` (Session's lazy-mode lifecycle callbacks and `_process`) and `.fledge/nest/architecture.md` (RLock-guarded state transitions):
- `src/stenographer/session.py` — `_on_model_loaded` and `_process`.
- `tests/test_session.py` — two new tests, following this file's existing `_make_session`/`_components`/`_process_prompt`/`_fake_llm_module` fixtures.

## Approach
- **F7 fix** in `_on_model_loaded`: inside the existing `with self._lock: if self._recording:` block, branch on `self._recording_source` exactly as `on_recording_start` already does (session.py ~L356-360): call `self._notification.show_listening_prompt()` when `self._recording_source == "prompt"`, else `self._notification.show_listening()` as today. No other change to this method (cue play, lock scope, exception handling all unchanged).
- **F8 fix** in `_process`: introduce a local flag (e.g. `prompt_llm_failed = False`) set to `True` inside the `except llm_module.LlmError` branch. At the function's existing final cue play —
  ```python
  if not self._stop_event.is_set():
      with contextlib.suppress(Exception):
          self._feedback.play("transcribe_done")
  ```
  — add the flag to the guard: `if not self._stop_event.is_set() and not prompt_llm_failed:`. Everything else in `_process` (the paste/type block that outputs the raw transcript on LLM failure, the `error` cue play inside the except block) is unchanged — this only suppresses the contradictory trailing success cue.

## Tests
Both in `tests/test_session.py`:
- `test_prompt_mode_lazy_model_load_shows_prompt_listening_notification` — using `_make_session(notification=MagicMock())`, set lazy ASR mode (`cfg.asr.mode = "lazy"`, `worker.is_model_loaded.return_value = False`), call `session.on_recording_start(source="prompt")` (which triggers `_on_model_loaded` registration via `worker.ensure_model_loaded`), then invoke the captured `on_loaded` callback directly (or call `session._on_model_loaded()` directly with `session._recording = True; session._recording_source = "prompt"` already set by `on_recording_start`), and assert `notification.show_listening_prompt.assert_called_once()` / `notification.show_listening.assert_not_called()`.
- `test_prompt_mode_llm_failure_plays_only_error_cue_not_transcribe_done` — using the existing `_process_prompt(session, c, text="hello world", raise_error=True)` helper, assert `c["feedback"].play.assert_any_call("error")` (as the existing `test_prompt_mode_falls_back_to_raw_transcript_on_llm_error` already does) AND additionally assert `"transcribe_done" not in [call.args[0] for call in c["feedback"].play.call_args_list]` — the new assertion this feather adds; also re-assert (already true today, but confirms no regression) that `injector.type_text`/`clipboard.copy` are still called with the raw transcript.

Implementation order: write both tests, run against the unchanged code and confirm they FAIL for the expected reason (first test: `show_listening` called instead of `show_listening_prompt`; second test: `transcribe_done` IS present in the play call list), then implement both fixes until they pass.

## Acceptance Criteria
- [ ] AC-1: The tests listed above were observed failing before implementation and pass after.
- [ ] AC-2: A prompt-mode recording whose first utterance triggers lazy model loading shows `show_listening_prompt()`, not `show_listening()`, once loading completes while still recording (satisfies PLM-003 FC-3).
- [ ] AC-3: On an LLM rewrite failure in prompt mode, `feedback.play("error")` fires and `feedback.play("transcribe_done")` does not, while the raw transcript is still typed and clipboarded (satisfies PLM-003 FC-4).
- [ ] AC-4: `.venv/bin/pytest -m "not integration"` passes with no regressions.
