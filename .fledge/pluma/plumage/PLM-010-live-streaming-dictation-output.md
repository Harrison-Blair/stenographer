---
id: PLM-010
title: Live streaming dictation output
status: hatched
priority: P1
authored: 2026-07-17T02:27:34Z
agent: fledge-orchestrate/planning
fledge_version: 0.5.8
---

# PLM-010: Live streaming dictation output

## Context
`live.py::LiveStreamer` already implements live streaming dictation (partials → re-decode → `asr/streaming.py::StreamingTranscriber`'s LocalAgreement-N commit → `HeuristicFormatter` → output), but `_emit()` (`live.py:226`) outputs each committed delta via `Injector.type_text(text, raw=True)` — the exact character-by-character typing mechanism behind all three of the user's original complaints (garbled characters in Electron apps, Return submitting terminal prompts, unrelated keybind collisions). Re-enabling streaming as it exists today (`session.py:155`: `self._streaming = bool(cfg.streaming.enabled and cfg.output.injection_method == "text")`, mutually exclusive with paste) would reintroduce every problem the user asked PLM-009 to eliminate. This plumage's core work is converting `_emit()` to use PLM-009's paste path (`ClipboardManager.copy(delta)` + `Injector.paste()`) instead of `type_text()`, and making streaming compatible with `injection_method == "paste"` rather than requiring `"text"`.

Per-word delta granularity was chosen deliberately, with a known cost accepted: the user runs `clipvault` (`wl-paste --watch clipvault store`, a clipboard-history daemon), so every committed word during streaming becomes a separate, permanent clipvault history entry — a single dictated sentence could add 10-20 fragment entries. The user was told this explicitly, offered coarser per-sentence deltas, backend-only (non-live) streaming, and pausing the clipvault watcher as alternatives, and chose per-word delta-paste anyway for maximum responsiveness. This is Context, not an open problem — it must not be "fixed" by a future reader.

The clipboard has two roles that collide under delta-paste: CLAUDE.md's invariant that the clipboard is always the independent fallback when injection fails assumes the clipboard holds the full transcript. Under delta-paste, the clipboard is also the *transport* for each in-flight delta — mid-utterance it holds only the latest word/chunk, not the full transcript. `_finish()` (`live.py:175-177`) already re-copies the full `self._typed` transcript once at utterance end today; this plumage keeps that behavior, so the "clipboard is the fallback" guarantee is restored the moment the utterance completes, but is only transiently untrue (holds a fragment, not the full transcript) while streaming is still in progress. This is accepted as inherent to the design, not a defect to engineer around.

This plumage depends on PLM-009's validation outcome for *how* deltas get pasted (chord/mechanism, behind `Injector.paste()`'s seam — this plumage's feathers never reference a specific chord or tool) and *whether* mid-utterance delta-paste happens at all: if PLM-009's validation fails and falls back to a static/manual `output.paste_chord`, this plumage degrades streaming to single-shot output at utterance end (same shape as today's non-streaming paste-mode chunk aggregation) rather than firing a possibly-wrong chord repeatedly mid-utterance. The user chose this conservative coupling explicitly over keeping streaming fully decoupled from PLM-009's outcome.

Two carried-forward concerns were investigated and resolved: (1) `audio.silence_rms_threshold=0.01` (below the user's own measured speech RMS, a known project issue) does not affect this plumage — `audio/capture.py` enforces that `on_segment` (RMS-based silence-flush) and `on_partial` (streaming's own signal) are mutually exclusive (`ValueError` if both are wired), and `_detect_silence` is only invoked when `on_segment` is set, so streaming mode never reads that threshold; the tail-silence guard streaming does use (`live.py::_cut_trailing_silence`) was already made self-relative to the recording's own noise floor by PLM-006 (fledged prior work), not the absolute threshold. (2) The never-revised/prefix invariant's exposure to focus change or cursor movement between deltas is inherited from today's typing-based streaming, not newly introduced by switching to paste — neither mechanism can detect or protect against the target window losing focus mid-utterance.

Streaming's real-hardware RTF/latency remains genuinely unmeasured, and delta-paste adds real per-delta cost (2× `wl-copy` + 1× `wtype` subprocess round-trips per committed word, vs. today's single in-process `type_text()` call) on top of that pre-existing unknown. This plumage includes a narrow measurement feather to capture that cost empirically rather than assume it — it measures and reports; it does not gate pass/fail on a latency threshold (no budget was requested or set).

## User Stories
- As a user, I want dictated text to appear incrementally while I'm still speaking (not just once at the end), so that live streaming actually behaves like streaming.
- As a user, I want that incremental output to use the same paste-based mechanism as the rest of dictation (never `wtype`'s character-by-character typing), so that streaming doesn't reintroduce the garbled-text, prompt-submission, and keybind problems I asked to eliminate.
- As a user, I want the heuristic spacing, capitalisation, and paragraph-break formatting I already rely on to keep working exactly the same way during live streaming.
- As a user, I want to know the real subprocess-latency cost of per-word delta-paste on my own hardware, so a future decision about whether it needs to be coarser isn't a guess.

## Functional Criteria
1. FC-1: `LiveStreamer._emit()` outputs each committed delta via `ClipboardManager.copy(delta)` followed by `Injector.paste()` (PLM-009's mechanism/chord, whatever it resolved to) instead of `Injector.type_text()`.
2. FC-2: `session.py`'s streaming-eligibility check (`self._streaming`, currently `cfg.streaming.enabled and cfg.output.injection_method == "text"`) is changed so streaming is compatible with `injection_method == "paste"` (the only supported injection method going forward per PLM-009's scope) rather than requiring `"text"`.
3. FC-3: `LiveStreamer._finish()` continues to re-copy the full accumulated transcript (`self._typed`) to the clipboard once at utterance end, exactly as it does today — restoring the "clipboard is the independent fallback" guarantee immediately after the utterance completes.
4. FC-4: If PLM-009's validation outcome is the universal-chord design: `LiveStreamer` fires a paste per committed delta as words are confirmed by the LocalAgreement-N committer (per-word granularity), exactly as `_emit()` does for typing today, just via paste instead of type.
5. FC-5: If PLM-009's validation outcome is the static/manual-chord fallback: `LiveStreamer` does not fire deltas mid-utterance; it accumulates committed text internally and performs exactly one clipboard-populate + paste at utterance end (`_finish()`), matching the shape of today's non-streaming paste-mode chunk-aggregation output. This is a single conditional check on which PLM-009 outcome shipped, not a runtime probe of chord correctness — `LiveStreamer` still calls `Injector.paste()` through its existing seam either way.
6. FC-6: `HeuristicFormatter` is reused unchanged via its existing `feed()`/`finalize()` append-only API — no changes to spacing, capitalisation, or paragraph-break logic.
7. FC-7: A measurement feather captures real wall-clock latency for one delta's full round-trip (`wl-copy` + `wl-copy --primary` if applicable + `wtype` paste trigger) on the user's actual hardware during a live dictation session, and reports the measured numbers (e.g. via logging or a bench-style script) — it does not gate pass/fail on any latency threshold.

## Acceptance Criteria
- [ ] AC-1: A test demonstrates `LiveStreamer._emit()` calls `ClipboardManager.copy()` and `Injector.paste()` for a committed delta, and never calls `Injector.type_text()`.
- [ ] AC-2: A test demonstrates streaming is selected (`Session._streaming` or equivalent) when `cfg.streaming.enabled` and `cfg.output.injection_method == "paste"`.
- [ ] AC-3: A test demonstrates `LiveStreamer._finish()` still re-copies the full transcript to the clipboard once at utterance end.
- [ ] AC-4: A test demonstrates that under the universal-chord PLM-009 outcome, each committed word/chunk delta triggers its own paste during the utterance (not just one at the end).
- [ ] AC-5: A test demonstrates that under the static/manual-chord PLM-009 fallback outcome, no paste fires until utterance end, where exactly one paste delivers the full accumulated transcript.
- [ ] AC-6: A test demonstrates `HeuristicFormatter`'s existing test suite passes unmodified — no behavioral change to its formatting rules.
- [ ] AC-7: The measurement feather produces a recorded real-hardware measurement of per-delta round-trip latency (documented in its molt evidence), with no pass/fail assertion tied to a latency number.
- [ ] AC-8: A test demonstrates the never-revised/prefix invariant still holds under delta-paste: the sequence of clipboard-populate-then-paste operations for committed deltas, concatenated, reconstructs the same text as the final batch transcript (the paste-mode analogue of the existing `test_live.py::test_prefix_invariant_M6` typed-delta check).
- [ ] AC-9: The full unit test suite (`.venv/bin/pytest -m "not integration"`) passes with no regressions.

## Out of Scope
- Any change to `asr/streaming.py`'s LocalAgreement-N commit algorithm itself.
- Any change to the non-streaming paste-mode chunk-aggregation pipeline (`Session._process_chunk`/`_aggregate_chunks`) or its RMS-based silence-flush behavior — untouched, unrelated to this plumage.
- Any change to `HeuristicFormatter`'s formatting rules.
- Expanding the latency-measurement feather (FC-7) into a full ASR-benchmarking suite, or adding a pass/fail latency budget/threshold — it is a narrow, one-time real-hardware measurement, reported only.
- Any mitigation for clipvault clipboard-history pollution (e.g. pausing the watcher, coarser deltas) — accepted, informed tradeoff, not this plumage's problem to solve.
- Supporting `injection_method == "text"` for streaming going forward — paste is the only injection method this feature targets (per PLM-009's scope); the old text-mode streaming code path may become dead code, which is a brooder-level implementation detail, not a functional requirement of this plumage.

## Open Questions
None — interrogation fully resolved this plumage's scope, including its conditional coupling to PLM-009's outcome.
