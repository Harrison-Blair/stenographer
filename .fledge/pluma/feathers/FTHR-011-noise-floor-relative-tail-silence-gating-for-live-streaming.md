---
id: FTHR-011
title: Noise-floor-relative tail-silence gating for live streaming
plumage: PLM-006
status: pipping
priority: P1
depends_on: []
authored: 2026-07-15T14:26:27Z
agent: fledge-orchestrate/planning
fledge_version: 0.4.0
---

# FTHR-011: Noise-floor-relative tail-silence gating for live streaming

## Description
`_cut_trailing_silence` (live.py) currently drops trailing sub-RMS audio from each interim re-decode window by comparing each 50ms step's RMS against the fixed `audio.silence_rms_threshold` config default (0.01). On a quiet mic (ambient RMS ~0.0002, speech RMS sometimes below 0.01 per repo memory `quiet-mic-rms.md`), this shaves or empties real trailing speech from every interim window, so live streaming never shows typed words while the user is still speaking on that mic — defeating its live-feedback purpose, even though the final unguarded decode at key-release is correct. This feather replaces the fixed-threshold comparison with a gate relative to the window's own observed noise floor (10th percentile of its per-step RMS values, recomputed fresh on every call — no new state on `LiveStreamer`), so the guard auto-scales to any mic. Satisfies PLM-006 FC-1–FC-5.

## Affected Modules
Per `.fledge/nest/architecture.md` (streaming/live driver) and repo memory `quiet-mic-rms.md` (never gate audio on absolute RMS defaults):
- `src/stenographer/live.py` — `_cut_trailing_silence` only; no other function in this file changes.
- `tests/test_live.py` — new/updated tests in the existing `# -- tail-silence guard --` section (already imports `_cut_trailing_silence` at module level).

## Approach
- Add a module-level constant `_NOISE_FLOOR_MULTIPLIER = 3` near the existing `_MIN_TRIM_SECONDS` / `_TAIL_CUSHION_SECONDS` constants.
- In `_cut_trailing_silence`, after computing `mono` and `step` (unchanged), first compute the full array of per-50ms-step RMS values for the window (walking forward in `step`-sized chunks, mirroring the existing backward-walk chunking so step boundaries match exactly what the trim loop already uses).
- If the number of steps is `< 10` (i.e. window shorter than 0.5s), return `window` unchanged immediately — this subsumes today's `window.shape[0] == 0` early return (0 steps is `< 10`), so that existing check can be folded into this one guard.
- Otherwise compute `floor = np.percentile(step_rms, 10)` and `cutoff = floor * _NOISE_FLOOR_MULTIPLIER`, then run the existing backward-walk trim loop unchanged except comparing each step's RMS against `cutoff` instead of `rms_threshold`.
- Drop the `rms_threshold` parameter from `_cut_trailing_silence`'s signature (it becomes unused) and update its sole call site in `LiveStreamer._step` to stop passing `self._cfg.audio.silence_rms_threshold`. No other change to `_step`, `_finish`, `_maybe_trim`, `capture.py`, or `audio.silence_rms_threshold` itself.
- Function stays pure: no reads/writes of `self` state; same window in → same output out, every call.

## Tests
All in `tests/test_live.py`'s `# -- tail-silence guard --` section:
- `test_cut_trailing_silence_trims_quiet_tail` and `test_cut_trailing_silence_keeps_loud_audio` (existing) — update call sites to drop `rms_threshold=` (signature changed); behavior for loud/normal audio must still pass unchanged.
- `test_cut_trailing_silence_all_silent_returns_empty` (existing) — reconsider: an all-silent window's every step is near the 10th-percentile floor itself, so nothing may register as "above cutoff" and the loop trims to empty — keep this test but verify it still holds under the new gate (it should, since floor*3 ≈ 0 for uniform near-zero RMS, though float noise means it isn't exactly 0 — assert the result is empty or near-empty, whichever the implementation actually produces once written).
- New: `test_cut_trailing_silence_preserves_quiet_mic_trailing_speech` — build a window with a quiet-mic speech segment (RMS ~0.001–0.005, e.g. `np.full(..., 0.003)`) followed by quiet ambient noise (RMS ~0.0002, e.g. low-amplitude random noise, NOT exact zero — a real ambient floor), long enough for >=10 steps of speech. Assert (a) `_cut_trailing_silence(window, SR, rms_threshold=<anything, now unused or param removed>)` under the OLD fixed-0.01 gate logic would have shaved/emptied the speech (documented in the test as the motivating contrast, verified by asserting the new result keeps substantially more trailing audio than a hardcoded 0.01-threshold trim would), and (b) under the new implementation the trailing speech segment is preserved (output length covers at least the full speech segment plus cushion, not just ambient-truncated).
- New: `test_cut_trailing_silence_normal_mic_still_trims_true_silence` — a loud speech segment (RMS ~0.5) followed by true silence (RMS ~0.0 or near-0), >=10 steps of silence; assert the silent tail is still trimmed (output length is bounded to roughly speech + cushion, not the full window), matching pre-fix behavior for a normal/loud mic.
- New: `test_cut_trailing_silence_short_window_returned_unchanged` — a window with fewer than 10 steps (< 0.5s at 16kHz, e.g. 0.3s) of arbitrary content (mix of loud and quiet) is returned unchanged (`out.shape[0] == window.shape[0]` and content identical), regardless of its RMS profile.
- New: `test_cut_trailing_silence_is_pure` — call `_cut_trailing_silence` twice with the identical window input (a window long enough to trigger a real trim, e.g. the quiet-mic or normal-mic fixture above) and assert both calls return identical output (`np.array_equal`), proving no cross-call state/memory affects the result.

Implementation order: update the two existing tests' call sites and write the four new tests first, run against the unchanged (pre-fix) code and confirm the new quiet-mic-preservation test FAILS for the expected reason (old absolute-0.01 gate shaves/empties the quiet speech), the short-window test currently passes trivially only for the `shape[0]==0` case (note: for a genuinely short-but-nonzero window like 0.3s, the OLD code does NOT skip — it still runs the RMS gate — so this test SHOULD fail pre-fix too, confirming the cold-start skip is new behavior), then implement until all pass.

## Acceptance Criteria
- [ ] AC-1: The tests listed above were observed failing before implementation (for the expected reasons — old absolute-threshold gate shaves quiet-mic speech; old code doesn't skip short-but-nonzero windows) and pass after.
- [ ] AC-2: `_cut_trailing_silence`'s gate is computed relative to the window's own 10th-percentile step RMS, multiplied by hardcoded `_NOISE_FLOOR_MULTIPLIER = 3`, not `audio.silence_rms_threshold` (satisfies PLM-006 FC-1, FC-2).
- [ ] AC-3: Windows with fewer than 10 steps (0.5s) are returned unchanged, regardless of content (satisfies PLM-006 FC-3).
- [ ] AC-4: `audio.silence_rms_threshold` and its use in `capture.py`'s mid-recording flush are untouched; no other `LiveStreamer` method changes (satisfies PLM-006 FC-4).
- [ ] AC-5: On the quiet-mic fixture, trailing speech is preserved where the old absolute-0.01 gate would have shaved/emptied it; on the normal/loud-mic fixture, true trailing silence is still trimmed (satisfies PLM-006 FC-5).
- [ ] AC-6: `_cut_trailing_silence` remains pure — two calls with an identical window input produce identical output.
- [ ] AC-7: `.venv/bin/pytest -m "not integration"` passes with no regressions.
