---
id: FTHR-006
title: Pitched-down start/stop cues for prompt mode
plumage: PLM-002
status: fledged
priority: P2
depends_on: [FTHR-004]
authored: 2026-07-11T06:00:05Z
agent: fledge-orchestrate/planning
fledge_version: 0.4.0
---

# FTHR-006: Pitched-down start/stop cues for prompt mode

## Description
Generate four new pre-synthesized WAV cue assets — the existing `ptt_on`/`toggle_on`/`ptt_off`/`toggle_off` tones, each pitched exactly two octaves down (frequency ÷ 4) — and have the prompt-mode hotkey's recording-start/stop cues play these instead of the shared ones, so the user can tell which mode just fired by sound alone. All other cues (`cancel`, `discard`, `error`, `segment`, `transcribe_done`, `model_loading`, `model_ready`) remain shared, unchanged. Satisfies PLM-002 FC-7.

## Affected Modules
Per `.fledge/nest/modules.md` (`scripts/gen_cues.py` cue synthesis; `audio/feedback.py:Feedback`/`CueName`) and `.fledge/nest/architecture.md` (`HotkeyListener` plays the `Transition.cue` it receives directly, via its constructor-injected `feedback` object — not through `Session`):
- `scripts/gen_cues.py` — `build_cues()`: add `ptt_on_prompt` (220.0 Hz, ÷4 of `ptt_on`'s 880.0 Hz), `toggle_on_prompt` (110.0 Hz, ÷4 of `toggle_on`'s 440.0 Hz), `ptt_off_prompt` (two 220.0 Hz beeps, ÷4 of `ptt_off`), `toggle_off_prompt` (two 110.0 Hz beeps, ÷4 of `toggle_off`) — same duration/gap/dBFS constants as their base tones, only frequency changes.
- `src/stenographer/audio/feedback.py` — extend the `CueName` Literal with the four new names so `Feedback.play()` type-checks them; no other change needed (`_resolve_path`/`play()` already resolve any `CueName` from `asset_root`, which the wheel's existing `assets/sounds/*.wav` glob already covers — no build config change needed).
- `src/stenographer/cli.py` — `_build_session()`: introduce a small cue-remapping adapter passed as the `feedback=` argument to the *second* (`prompt_binding`) `HotkeyListener` only — it remaps `"ptt_on"→"ptt_on_prompt"`, `"toggle_on"→"toggle_on_prompt"`, `"ptt_off"→"ptt_off_prompt"`, `"toggle_off"→"toggle_off_prompt"` before delegating to the real shared `Feedback.play()`, and passes every other cue name through unchanged. The dictate-mode listener keeps using the real `Feedback` directly, untouched.
- `tests/test_feedback.py` / a new small test module for the adapter, plus `scripts/gen_cues.py` if it has its own tests (none observed per `.fledge/nest/testing.md`) — new assertions on the four new tones' frequencies; `tests/test_hotkey.py`-style listener test extended (or a focused new test) to assert the adapter's remapping.

## Approach
- This keeps `HotkeyStateMachine`/`Transition` completely untouched — the state machine still only ever emits the generic cue names (`"ptt_on"`, `"toggle_on"`, etc.); the remapping is a thin adapter at the wiring boundary in `cli.py`, exactly where the second listener is already constructed (per FTHR-004). This is the smallest change that achieves per-mode cues without teaching the pure state machine about modes.
- The adapter can be a tiny class or closure with a `.play(name: CueName) -> None` method matching `Feedback`'s public surface exactly (structural typing — `HotkeyListener` only calls `.play(name)` on whatever `feedback` object it was given), so no `Feedback`/`HotkeyListener` code changes at all.
- `gen_cues.py` changes are purely additive: four new dict entries in `build_cues()`, generated the same way `scripts/gen_cues.py` is already run manually to (re)populate `src/stenographer/assets/sounds/`. Running the script writes the four new WAV files as a normal part of this feather's implementation (not a separate manual step left to the user).

## Tests
- `test_build_cues_includes_pitched_down_prompt_variants` (new, alongside wherever `gen_cues.py`'s `build_cues()` is most naturally tested — following `.fledge/nest/testing.md`'s note that no dedicated test file was observed for this script; add one if none exists, `tests/test_gen_cues.py`) — asserts `build_cues()` returns the four new keys, and that each new tone's dominant frequency is exactly the source tone's frequency ÷ 4 (verifiable via FFT peak or by reusing the same `tone()` helper with the expected frequency and comparing sample arrays).
- `test_prompt_cue_adapter_remaps_start_stop_cues` — the adapter's `.play("ptt_on")` calls the underlying `Feedback.play("ptt_on_prompt")`; same for `toggle_on`/`ptt_off`/`toggle_off`.
- `test_prompt_cue_adapter_passes_through_other_cues_unchanged` — the adapter's `.play("cancel")` (and `"discard"`, `"error"`, etc.) calls the underlying `Feedback.play()` with the same, unmapped name.
- `test_dictate_listener_uses_unmapped_feedback` — regression guard: the dictate-mode listener in `_build_session()` still receives the real `Feedback` directly (or an adapter that is the identity for all cue names), never producing pitched-down cues for the existing hotkey.

Implementation order: write all tests above, run against the unchanged code and confirm they fail for the expected reason (new cue keys/assets don't exist; no adapter exists yet), then implement `gen_cues.py`'s new entries (and regenerate the WAV assets), the `CueName` extension, and the adapter until all pass.

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before implementation and pass after.
- [x] AC-2: `ptt_on_prompt`/`toggle_on_prompt`/`ptt_off_prompt`/`toggle_off_prompt` WAV assets exist at exactly ÷4 the frequency of their base tones (satisfies PLM-002 FC-7).
- [x] AC-3: A prompt-mode recording start/stop plays the pitched-down cue variants; all other cues (cancel/discard/error/etc.) remain shared and unchanged for both modes (satisfies PLM-002 FC-7).
- [x] AC-4: The existing dictate-mode hotkey's cues are unaffected (regression guard).
- [x] AC-5: `.venv/bin/pytest -m "not integration"` passes with no regressions.
