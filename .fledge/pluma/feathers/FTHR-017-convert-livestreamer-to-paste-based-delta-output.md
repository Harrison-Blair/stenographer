---
id: FTHR-017
title: Convert LiveStreamer to paste-based delta output
plumage: PLM-010
status: egg
priority: P1
depends_on: [FTHR-016]
authored: 2026-07-17T02:35:14Z
agent: fledge-orchestrate/planning
fledge_version: 0.5.8
---

# FTHR-017: Convert LiveStreamer to paste-based delta output

## Description
Converts `LiveStreamer` from typing-based to paste-based delta output, and makes streaming compatible with `injection_method == "paste"`. Depends on FTHR-016 (PLM-009), so `Injector.paste()`/`ClipboardManager.copy()` already have their final (branch-selected) behavior — this feather calls them through their existing seam and does not need to know or check which of FTHR-016's two branches shipped, **except** for one explicit conditional: whether deltas fire mid-utterance at all, which depends on FTHR-015's `RESULT:` line (read from `.fledge/molt/FTHR-015.md`, the same source FTHR-016 branched on):

- **If FTHR-015's `RESULT:` was 3/3 pass (universal chord shipped):** `LiveStreamer._emit()` fires a `ClipboardManager.copy(delta)` + `Injector.paste()` round-trip per committed word/chunk, as words are confirmed by the LocalAgreement-N committer — per-word granularity, live/incremental (PLM-010 FC-4/AC-4).
- **If FTHR-015's `RESULT:` was the fallback:** `LiveStreamer` does not paste mid-utterance at all; it accumulates committed text internally (as it already does in `self._typed`) and performs exactly one `ClipboardManager.copy()` + `Injector.paste()` at `_finish()` — matching the shape of today's non-streaming paste-mode chunk aggregation (PLM-010 FC-5/AC-5).

Either branch: `_finish()` continues to re-copy the full accumulated transcript to the clipboard once at utterance end (already existing behavior, `live.py:175-177`), restoring the "clipboard is the independent fallback" guarantee immediately after the utterance completes (PLM-010 FC-3/AC-3). `HeuristicFormatter` is reused unchanged via its existing `feed()`/`finalize()` API — no formatting-logic changes (PLM-010 FC-6/AC-6).

## Affected Modules
- `live.py::LiveStreamer._emit()` — converts from `Injector.type_text(text, raw=True)` to `ClipboardManager.copy(delta)` + `Injector.paste()`; gains the per-word-vs-single-shot branch.
- `live.py::LiveStreamer._finish()` — unchanged behavior (full-transcript re-copy), verify it still holds under the new `_emit()`.
- `session.py:155` — `self._streaming = bool(cfg.streaming.enabled and cfg.output.injection_method == "text")` changes to check `"paste"` instead of `"text"`.
- See `.fledge/nest/architecture.md` (three-pipeline routing, never-revised invariant), `.fledge/nest/modules.md` → `src-session-live` for existing conventions.

## Approach
Read `.fledge/molt/FTHR-015.md`'s `RESULT:` line once, at implementation time (not at runtime — this is a build-time branch decision baked into the shipped code, exactly like FTHR-016's branch, not a runtime feature flag) to decide which of the two `_emit()`/`_finish()` shapes to build. Do not build both and switch on a config value — that reintroduces the per-app-detection complexity already ruled out.

For the per-word branch: keep `_emit()`'s existing signature and call site in `_step()`/`_finish()` unchanged; only its body changes from a single `type_text()` call to `clipboard.copy(text)` then `injector.paste()`, with the same truthy-return bookkeeping (`self._typed += text` only on success) and the same `max_chars` early-return guard already present. For the single-shot branch: `_emit()` no longer calls `clipboard`/`injector` per-delta at all — it just accumulates `self._typed += text` (formatting still applied via `self._formatter.feed(delta)` exactly as today, since `HeuristicFormatter` must still see every delta to compute correct spacing/capitalisation/paragraph breaks even though output is deferred); `_finish()` performs the single `copy()`+`paste()` call using the fully accumulated, fully-formatted text.

The prefix-invariant test (PLM-010 AC-8) is the paste-mode analogue of the existing `test_live.py::test_prefix_invariant_M6`: instead of reconstructing the typed string from `type_text()` call arguments, reconstruct it from the sequence of `clipboard.copy()` call arguments (per-word branch) or from the single `_finish()`-time call (single-shot branch), and assert it matches the final batch transcript.

## Tests
- `test_live.py::test_emit_uses_paste_not_type_text` — asserts `LiveStreamer._emit()` never calls `Injector.type_text()`; calls `ClipboardManager.copy()`/`Injector.paste()` instead.
- `test_session.py::test_streaming_enabled_with_paste_injection` — asserts `Session._streaming` is `True` when `cfg.streaming.enabled` and `cfg.output.injection_method == "paste"` (not requiring `"text"`).
- `test_live.py::test_finish_recopies_full_transcript` — asserts `_finish()` still calls `clipboard.copy()` with the complete accumulated transcript at utterance end.
- Per-word branch only: `test_live.py::test_delta_pastes_fire_per_committed_word` — asserts each committed delta during `_step()` triggers its own `copy()`+`paste()` call pair, not deferred to the end.
- Single-shot branch only: `test_live.py::test_no_paste_until_finish` — asserts no `copy()`/`paste()` call occurs during `_step()`; exactly one pair occurs at `_finish()`, carrying the full accumulated text.
- `test_live.py::test_prefix_invariant_paste_mode` — the paste-mode analogue of `test_prefix_invariant_M6`: reconstructs the delivered text from the sequence of `copy()` calls (or the single `_finish()` call) and asserts it equals the final batch transcript for the same audio.
- `test_formatter.py` (existing suite) — run unmodified to confirm no regression to `HeuristicFormatter`.
- Implementation order is fixed: (1) write the tests above (only for the branch FTHR-015 selected, plus the branch-independent ones); (2) run them against the unchanged code and confirm they FAIL for the expected reason; (3) implement until they pass.

## Acceptance Criteria
- [ ] AC-1: The tests listed above were observed failing before implementation and pass after.
- [ ] AC-2: `LiveStreamer._emit()` never calls `Injector.type_text()` — satisfies PLM-010 FC-1/AC-1.
- [ ] AC-3: `Session._streaming` is selected on `injection_method == "paste"` — satisfies PLM-010 FC-2/AC-2.
- [ ] AC-4: `_finish()` still re-copies the full transcript at utterance end — satisfies PLM-010 FC-3/AC-3.
- [ ] AC-5: If FTHR-015's `RESULT:` was 3/3 pass: each committed delta fires its own paste during the utterance — satisfies PLM-010 FC-4/AC-4.
- [ ] AC-6: If FTHR-015's `RESULT:` was the fallback: no paste fires until `_finish()`, which delivers the full transcript in one call — satisfies PLM-010 FC-5/AC-5.
- [ ] AC-7: `HeuristicFormatter`'s existing test suite passes unmodified — satisfies PLM-010 FC-6/AC-6.
- [ ] AC-8: The paste-mode prefix-invariant test passes, demonstrating the never-revised guarantee holds under delta-paste — satisfies PLM-010 AC-8.
- [ ] AC-9: The full unit test suite (`.venv/bin/pytest -m "not integration"`) passes with no regressions.
