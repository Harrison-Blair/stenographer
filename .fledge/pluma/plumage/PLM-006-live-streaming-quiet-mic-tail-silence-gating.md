---
id: PLM-006
title: Live streaming quiet-mic tail-silence gating
status: hatched
priority: P1
authored: 2026-07-15T05:15:11Z
agent: fledge-orchestrate/planning
fledge_version: 0.4.0
---

# PLM-006: Live streaming quiet-mic tail-silence gating

## Context
Live streaming's interim re-decodes (`LiveStreamer._step`, live.py) call `_cut_trailing_silence` to trim probable-silence audio off the tail of each re-decode window before running it through the ASR model — a stand-in for the per-segment `no_speech_prob` hallucination gate that word-level decoding loses. Today that guard compares each 50ms step's RMS against the fixed `audio.silence_rms_threshold` config default (0.01). Per repo memory (quiet-mic-rms.md), on a quiet mic (ambient RMS ~0.0002, speech RMS sometimes below 0.01 — the exact default) every interim window's tail reads as silent: the tail gets shaved, or the whole window returns empty. Nothing types while recording continues; words only appear once the final, unguarded decode runs at key-release — defeating live streaming's entire live-feedback purpose for that mic, even though the eventual transcript is correct (the final decode isn't gated).

This plumage replaces the fixed-threshold comparison with one relative to the recording's own observed noise floor, so the guard auto-scales to any mic without a user needing to hand-tune a config value — directly addressing the memory's standing guidance to never gate audio on absolute RMS defaults in this repo.

## User Stories
- As a user with a quiet microphone, I want live-streamed dictation to actually show typed words while I'm still speaking (not just at the end), so the streaming feature behaves as advertised regardless of my mic's absolute recording level.
- As a user with a normal/loud microphone, I want the trailing-silence guard to keep working exactly as it does today — real trailing silence still gets trimmed, hallucination-over-silence is still prevented.

## Functional Criteria
1. FC-1: `_cut_trailing_silence`'s silence gate is computed relative to the current window's own noise floor — the 10th percentile of that window's per-50ms-step RMS values — rather than the fixed `audio.silence_rms_threshold` config default.
2. FC-2: The effective cutoff for a given window is `floor * 3` (a hardcoded module-level constant, not user-configurable), where `floor` is that window's 10th-percentile step RMS.
3. FC-3: For windows shorter than 10 steps (0.5s of audio), the cut is skipped entirely and the window is returned unchanged — too little audio exists to estimate a reliable floor, and skipping guarantees early real speech is never shaved.
4. FC-4: `audio.silence_rms_threshold` itself, and its other use in `capture.py`'s mid-recording segment-flush silence detection, are unchanged — only `_cut_trailing_silence`'s internal gating logic changes; its function signature may drop the now-unused `rms_threshold` parameter if no longer needed, or keep it unused-but-compatible — implementer's call, noted as a minor detail, not a functional criterion.
5. FC-5: On a quiet-mic audio fixture (speech RMS ~0.001-0.005, ambient ~0.0002, per repo memory), real trailing speech in an interim window is preserved (not shaved) where the old fixed-0.01 threshold would have shaved or emptied it. On a normal-mic fixture (speech well above 0.01), true trailing silence is still trimmed as before.

## Acceptance Criteria
- [ ] AC-1: A test demonstrates that on a quiet-mic fixture (speech RMS ~0.001-0.005, ambient ~0.0002) where the OLD absolute-0.01 behavior would shave real trailing speech or return an empty window, the new floor-relative gate preserves that trailing speech.
- [ ] AC-2: A test demonstrates that on a normal/loud-mic fixture (speech well above 0.01), genuine trailing silence is still trimmed, matching pre-fix behavior for that case.
- [ ] AC-3: A test demonstrates that a window shorter than 10 steps (0.5s) is returned unchanged regardless of its content (no cut applied).
- [ ] AC-4: A test demonstrates `_cut_trailing_silence` remains a pure function with no new state on `LiveStreamer` (i.e. calling it twice with the same window input yields the same output — no hidden cross-call memory).
- [ ] AC-5: The full unit test suite (`.venv/bin/pytest -m "not integration"`) passes with no regressions to existing live-streaming or silence-detection behavior.

## Out of Scope
- Any change to `audio.silence_rms_threshold` itself or its other use in `capture.py`'s mid-recording segment-flush silence detection.
- Making the noise-floor multiplier or the minimum-window-length (10 steps) user-configurable — both are hardcoded constants per this interrogation.
- Any change to `LiveStreamer`'s window-trimming/rebasing (`_maybe_trim`), `max_buffer_seconds`, or other windowing logic beyond `_cut_trailing_silence` itself.
- Any change to the final (unguarded) decode path (`_finish`) — it already skips this guard entirely.
- General RTF/performance tuning of streaming.

## Open Questions
None — resolved during interrogation: floor = 10th percentile of the current window's per-step RMS (stateless, recomputed per call); multiplier K=3, hardcoded constant `_NOISE_FLOOR_MULTIPLIER`; windows under 10 steps (0.5s) skip the cut entirely; `audio.silence_rms_threshold` untouched elsewhere; priority P1.
