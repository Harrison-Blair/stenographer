---
id: FTHR-005
title: Distinct per-stage notifications for prompt mode
plumage: PLM-002
status: hatching
priority: P2
depends_on: [FTHR-004]
authored: 2026-07-11T05:57:54Z
agent: fledge-orchestrate/planning
fledge_version: 0.4.0
---

# FTHR-005: Distinct per-stage notifications for prompt mode

## Description
Add prompt-mode-specific desktop notification wording for every stage of its pipeline (listening, transcribing, rewriting via the local LLM, success, and failure), wired into the `source == "prompt"` branches FTHR-004 established, so the user can always tell from the notification text alone that prompt mode (not the existing dictation mode) fired, and what stage it's at. Satisfies PLM-002 FC-5 in full, and completes the notification half of FC-4 (the LLM-failure fallback path already types the raw transcript per FTHR-004; this feather adds the "Prompt-crafting failed — using raw transcript" notification alongside it).

## Affected Modules
Per `.fledge/nest/entry-points.md` (`DesktopNotification`'s existing `show_listening()`/`show_transcribing()`/etc. stage-method pattern) and `.fledge/nest/conventions.md` (async, non-blocking notification queue):
- `src/stenographer/notification.py` — `DesktopNotification`: add new stage methods, following the exact style of the existing ones (`self._enqueue(text, timeout_ms)`).
- `src/stenographer/session.py` — replace the mode-agnostic `show_listening()`/`show_transcribing()` calls with mode-branched calls at the `source == "prompt"` sites FTHR-004 introduced (`on_recording_start`, `on_recording_stop`, and the `_process` LLM-call region); dictate-mode call sites are unchanged.
- `tests/test_notification.py` — new tests for the added methods, following its existing per-method test pattern.
- `tests/test_session.py` — extend FTHR-004's prompt-mode tests to assert the correct notification method fires at each stage (rather than adding wholly new test files).

## Approach
- New `DesktopNotification` methods, mirroring the existing ones' persistent (`timeout_ms=0`) vs. transient (`timeout_ms>0`) split:
  - `show_listening_prompt()` — persistent, e.g. `"Listening (prompt)…"`.
  - `show_transcribing_prompt()` — persistent, e.g. `"Transcribing (prompt)…"`.
  - `show_rewriting()` — persistent, `"Rewriting with local LLM…"`.
  - `show_prompt_ready()` — transient (e.g. 3000ms), `"Prompt ready"`.
  - `show_prompt_failed()` — transient (e.g. 5000ms), `"Prompt-crafting failed — using raw transcript"`.
- In `Session`, at each `source == "prompt"` branch point:
  - `on_recording_start`: call `show_listening_prompt()` instead of `show_listening()`.
  - `on_recording_stop`: call `show_transcribing_prompt()` instead of `show_transcribing()`.
  - `_process`, immediately before the `llm.rewrite_prompt()` call: call `show_rewriting()`.
  - `_process`, on success: call `show_prompt_ready()` (fires before the existing queue-drain `hide()` logic in `_process_utterance_queue`, which still applies unchanged — the transient notification expires on its own timeout, mirroring how `show_startup`/`show_model_unloaded` are already used as fire-and-forget transients rather than persistent state).
  - `_process`, on `LlmError` (the `except` branch FTHR-004 added): call `show_prompt_failed()` in addition to the existing `feedback.play("error")` cue.
- All calls remain guarded by the existing `if self._notification is not None:` pattern already used throughout `Session`.

## Tests
- In `tests/test_notification.py` (new tests, following the existing per-method pattern: construct with a stubbed/mocked notify-send availability, call the method, assert the enqueued text/timeout):
  - `test_show_listening_prompt_enqueues_persistent_notification`
  - `test_show_transcribing_prompt_enqueues_persistent_notification`
  - `test_show_rewriting_enqueues_persistent_notification`
  - `test_show_prompt_ready_enqueues_transient_notification`
  - `test_show_prompt_failed_enqueues_transient_notification`
  - `test_prompt_stage_wording_distinct_from_dictate_stage_wording` — asserts none of the five new methods' text strings match `show_listening()`'s or `show_transcribing()`'s text, pinning down the "distinguishable from the existing mode's notifications" requirement directly (satisfies PLM-002 AC-4's distinguishability half).
- In `tests/test_session.py` (extending FTHR-004's mocked-notification fixtures):
  - `test_prompt_mode_recording_start_shows_prompt_listening_notification`
  - `test_prompt_mode_recording_stop_shows_prompt_transcribing_notification`
  - `test_prompt_mode_llm_call_shows_rewriting_notification`
  - `test_prompt_mode_success_shows_prompt_ready_notification`
  - `test_prompt_mode_llm_failure_shows_prompt_failed_notification`
  - `test_dictate_mode_notifications_unchanged` — regression guard: a `source="dictate"` recording still calls the original `show_listening()`/`show_transcribing()`, never the new prompt-specific methods.

Implementation order: write all tests above, run against the unchanged code and confirm they fail for the expected reason (new methods don't exist yet; Session still calls the generic methods for prompt-mode recordings), then implement until all pass.

## Acceptance Criteria
- [ ] AC-1: The tests listed above were observed failing before implementation and pass after.
- [ ] AC-2: Every stage of a prompt-mode recording (listening, transcribing, rewriting, success, failure) shows a notification worded distinctly from the equivalent dictate-mode notification (satisfies PLM-002 FC-5, AC-4).
- [ ] AC-3: An LLM-call failure shows the "Prompt-crafting failed — using raw transcript" notification alongside the existing error cue from FTHR-004 (completes PLM-002 FC-4, AC-2).
- [ ] AC-4: Dictate-mode notification behavior is unchanged (regression guard).
- [ ] AC-5: `.venv/bin/pytest -m "not integration"` passes with no regressions.
