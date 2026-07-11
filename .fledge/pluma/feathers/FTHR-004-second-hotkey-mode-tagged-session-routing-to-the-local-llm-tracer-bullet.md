---
id: FTHR-004
title: "Second hotkey + mode-tagged Session routing to the local LLM (tracer bullet)"
plumage: PLM-002
status: egg
priority: P1
depends_on: [FTHR-002]
authored: 2026-07-11T05:55:59Z
agent: fledge-orchestrate/planning
fledge_version: 0.4.0
---

# FTHR-004: Second hotkey + mode-tagged Session routing to the local LLM (tracer bullet)

## Description
Wire a second, independent hotkey trigger (Right Shift, via `hotkey.prompt_binding` from FTHR-002) that shares the existing `Session` instance with the current dictation hotkey, tags each recording with which mode triggered it, and — for prompt-mode recordings — calls the LLM client's `rewrite_prompt()` interface (FTHR-003's contract; mocked in this feather's own tests, not a real dependency) on the completed transcript before typing/copying the result, falling back to the raw transcript if the call raises. This is the thin, real, end-to-end slice: after this feather, pressing Right Shift and speaking produces LLM-rewritten output through the existing recording/transcription machinery, proving the architecture. Polish (distinct notifications, pitched cues) is deliberately deferred to FTHR-005/FTHR-006. Satisfies PLM-002 FC-1, FC-2 (session-side integration), FC-4 (fallback behavior), and FC-6 (no streaming for this mode).

## Affected Modules
Per `.fledge/nest/architecture.md` (Session as single lock-guarded orchestrator; hotkey layer's "one binding, one state machine" pattern) and `.fledge/nest/entry-points.md` (`_build_session()`'s wiring, `Session` constructor/callback surface):
- `src/stenographer/session.py` — `Session`: add a second optional listener slot and its lifecycle (start/stop); tag recordings with which hotkey triggered them; branch the completed-transcript output step for prompt-mode recordings.
- `src/stenographer/cli.py` — `_build_session()`: construct a second `HotkeyBinding`/`HotkeyStateMachine`/`HotkeyListener` from `cfg.hotkey.prompt_binding`, wired to the same `Session`, with its callbacks tagged as the prompt-mode source.
- `src/stenographer/llm.py` — imported by `session.py` for the `rewrite_prompt(cfg.llm, transcript) -> str` call (FTHR-003's contract; this feather's own tests mock this import, so it does not require FTHR-003 to be merged first — only its agreed signature).
- `tests/test_session.py` — new tests for mode-tagged routing; existing tests (recording lifecycle, `_process`, cancel/discard) must keep passing unchanged since this feather is additive.

## Approach
- **Mode tag, distinct from the existing `mode: Literal["ptt", "toggle"]` parameter** (which already means push-to-talk-vs-toggle trigger timing): introduce a separate `source: Literal["dictate", "prompt"]` parameter, defaulting to `"dictate"` everywhere it's threaded, so existing call sites and tests are unaffected unless explicitly exercising prompt mode. Thread it through `on_recording_start(source=...)`, `on_recording_stop(mode, source=...)`, and the batch queue item / `_process(samples, mode, abort, source)`.
- **Second listener wiring in `_build_session()`:** build a second `HotkeyBinding.parse(cfg.hotkey.prompt_binding)`, a second `HotkeyStateMachine` (same `toggle_threshold_seconds`/`double_tap_window_seconds` per the accepted "shared timing" decision), and a second `HotkeyListener`, whose `on_start`/`on_stop`/`on_toggle_off` callbacks are bound to `Session` methods with `source="prompt"` (e.g. via `functools.partial` or a small closure), while the existing listener's callbacks keep the implicit `source="dictate"` default. Both listeners share `session.lock` and the same `feedback`/`cancel_binding` wiring pattern as today.
- **Session listener lifecycle:** add `attach_prompt_listener()` alongside the existing `attach_listener()`, and extend `start_listener()`/`stop()` to start/stop both listeners when present, so `Session` remains the single lifecycle owner (per `architecture.md`'s "Session is the single orchestrator").
- **No streaming for prompt-mode recordings (FC-6):** in `on_recording_start`, when `source == "prompt"`, always take the non-streaming path regardless of the global `self._streaming` flag (streaming is presently a single cfg-wide setting; prompt mode must never use it even if the primary dictation hotkey has streaming enabled).
- **No mid-recording silence-triggered flush segments for prompt-mode recordings:** pass `on_segment=None` to `recorder.start()` when `source == "prompt"`, regardless of `self._silence_detection` — a prompt-mode utterance must be transcribed as one contiguous batch (one LLM call per utterance), not split into multiple independently-flushed-and-typed segments the way normal dictation optimizes for latency. This mirrors how one-shot mode already disables silence-detection for an analogous reason.
- **Output branch in `_process`:** for `source == "prompt"`, skip the per-segment partial-injection loop entirely (no typing happens until the full result is ready — consistent with "output produced once" FC-6); after the existing silence-filtering/formatting logic produces the final `text`, call `llm.rewrite_prompt(self._cfg.llm, text)` inside a `try/except LlmError`. On success, replace `text` with the returned rewritten string before the existing paste/text output logic runs unchanged. On `LlmError`, log at ERROR, keep the original raw `text` as-is, and play the existing `"error"` feedback cue (`self._feedback.play("error")`) so a failure is audible — the *desktop notification* wording for this failure path is FTHR-005's responsibility, not this feather's; this feather only guarantees the fallback behavior itself (PLM-002 FC-4) and an audible signal, using the mechanism already in place for other transcription failures.
- **Interface discipline:** this feather imports and calls `stenographer.llm.rewrite_prompt(cfg: LlmConfig, transcript: str) -> str`, raising `LlmError` on failure — the exact contract FTHR-003 defines. In this feather's own tests, that import is mocked (`unittest.mock.patch`), so test authorship and passing do not require FTHR-003 to be implemented first (they were dispatched in parallel); real end-to-end behavior is only exercised once both are merged.

## Tests
All in `tests/test_session.py`, following the file's existing `_make_session()`/mock-everything conventions:
- `test_prompt_mode_recording_calls_rewrite_prompt` — completing a prompt-mode recording calls the (mocked) `rewrite_prompt` with the transcribed text and `cfg.llm`.
- `test_prompt_mode_types_rewritten_text_not_raw_transcript` — the mocked `rewrite_prompt`'s return value is what gets typed/copied, not the raw transcript (satisfies PLM-002 AC-1).
- `test_prompt_mode_falls_back_to_raw_transcript_on_llm_error` — when the mocked `rewrite_prompt` raises `LlmError`, the raw transcript is typed/copied instead, and the error feedback cue plays (satisfies PLM-002 AC-2, partially — cue only; notification wording is FTHR-005).
- `test_dictate_mode_unaffected_by_prompt_mode_addition` — a `source="dictate"` (or default) recording never calls `rewrite_prompt` and behaves exactly as today (regression guard).
- `test_prompt_mode_hotkey_independent_trigger_rules` — the prompt-mode listener's push-to-talk, toggle, and double-tap-discard behavior mirror the dictate listener's (constructed with the same `HotkeyStateMachine` parameters), and firing one hotkey's callbacks does not affect the other's state (satisfies PLM-002 AC-3).
- `test_prompt_mode_never_streams` — with `cfg.streaming.enabled=True` and `cfg.output.injection_method="text"` (conditions that would normally enable streaming), a prompt-mode recording still takes the non-streaming batch path (satisfies PLM-002 FC-6).
- `test_prompt_mode_disables_silence_flush_segments` — with `cfg.audio.silence_detection=True`, a prompt-mode recording's `recorder.start()` call receives `on_segment=None`.
- Existing tests in `test_session.py` (recording lifecycle, `_process`, cancel/discard, live-streaming wiring) are re-run unchanged as the regression guard for FC-1's "usable concurrently with, independently of" requirement.

Implementation order: write all new tests above, run against the unchanged code and confirm they fail for the expected reason (no `source` parameter exists yet; no second listener; no `llm` import), then implement until they and the full existing `test_session.py` suite pass.

## Acceptance Criteria
- [ ] AC-1: The tests listed above were observed failing before implementation and pass after.
- [ ] AC-2: A prompt-mode recording's typed/copied output is the (mocked, in this feather's tests) LLM's rewritten text, not the raw transcript (satisfies PLM-002 FC-2, AC-1).
- [ ] AC-3: On an LLM-call failure, the raw transcript is typed/copied instead and the existing error cue plays (satisfies PLM-002 FC-4, AC-2 partially).
- [ ] AC-4: The prompt-mode hotkey's PTT/toggle/double-tap-discard behavior matches the dictate hotkey's, and the two hotkeys operate independently (satisfies PLM-002 FC-1, AC-3).
- [ ] AC-5: Prompt-mode recordings never use the live/streaming path and never emit mid-recording silence-flush segments, regardless of global streaming/silence-detection config (satisfies PLM-002 FC-6).
- [ ] AC-6: `.venv/bin/pytest -m "not integration"` passes with no regressions to any existing `test_session.py`/`test_hotkey.py` behavior.
