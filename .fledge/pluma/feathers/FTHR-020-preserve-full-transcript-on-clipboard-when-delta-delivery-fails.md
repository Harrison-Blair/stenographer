---
id: FTHR-020
title: Preserve full transcript on clipboard when delta delivery fails
plumage: PLM-010
status: hatching
priority: P2
depends_on: [FTHR-017]
authored: 2026-07-17T03:30:36Z
agent: fledge-orchestrate/planning
fledge_version: 0.5.8
---

# FTHR-020: Preserve full transcript on clipboard when delta delivery fails

## Description
Closes a text-loss gap found during FTHR-017's review and confirmed by the user
before that feather merged. It is a follow-up, not a defect report: FTHR-017 is
spec-compliant and its behavior is strictly better than what preceded it.

FTHR-017 made `LiveStreamer._emit()` latch output off for the rest of an
utterance once a delta fails to deliver (`self._delivery_failed`), so the
delivered text always stops at a clean prefix boundary rather than continuing
past a gap. That latch is correct and must be preserved — it is what upholds
PLM-010's never-revised invariant, and this feather must not weaken or remove it.

The gap is what happens to the *undelivered remainder*. `self._typed` only grows
on a successful delivery, so once the latch engages `_typed` freezes at the
delivered prefix. `_finish()` then copies `self._typed` to the clipboard. Net
effect for a transcript of "One two three" whose second delta fails: the cursor
holds "One", the clipboard holds "One", and "two three" is lost — it is neither
pasted nor recoverable.

That contradicts the guarantee `CLAUDE.md` states for this codebase — "The
clipboard is populated independently, so it's the fallback when injection fails"
— precisely in the case the fallback exists to cover. This feather makes the
clipboard carry the **full transcript** whenever delivery latched, so the user
can paste the remainder manually.

Scope note on PLM-010 AC-3: that criterion ("`_finish()` still re-copies the full
transcript") is already satisfied and tested by FTHR-017's
`test_finish_recopies_full_transcript`, because on the happy path `_typed` *is*
the full transcript. The failure path is simply outside what any existing PLM-010
criterion describes. This feather extends that guarantee to hold on the failure
path too; it does not re-open or invalidate AC-3.

## Affected Modules
- `live.py::LiveStreamer._finish()` — the clipboard re-copy at `live.py:180-184`
  currently copies `self._typed` (the delivered prefix). It must copy the full
  formatted transcript when `self._delivery_failed` is set.
- `live.py::LiveStreamer._emit()` — read-only for this feather in behavioral
  terms: the `_delivery_failed` latch and the "no paste past a gap" rule are
  FTHR-017's and must survive unchanged. Only the accumulation needed to
  reconstruct the full transcript may be added.
- Out of scope: `output/clipboard.py` (`ClipboardManager.copy()`'s strict return
  must not be loosened — see the note below), `output/formatter.py`'s rules,
  `asr/streaming.py`'s commit algorithm, and `session.py`.
- See `.fledge/nest/architecture.md` (never-revised invariant, three-pipeline
  routing), `.fledge/nest/modules.md` → `src-session-live`, and
  `.fledge/molt/FTHR-017.md` for the latch's rationale and evidence.

## Approach
`_finish()` already computes the final formatted text on the path that feeds
`_emit()` (`self._formatter.feed(delta) + self._formatter.finalize()`). The
change is to make the full formatted transcript available at the clipboard
re-copy regardless of what was delivered.

Prefer the smallest change that reads honestly. The likely shape: accumulate the
formatted text into a separate attribute (e.g. `self._transcript`) in `_emit()`
independently of delivery success, leaving `self._typed` as the record of what
was actually delivered (`_typed` is `_finish()`'s return value and the basis of
the prefix invariant — do not conflate the two, and do not change what `_typed`
means). Then `_finish()` copies `self._transcript` **when and only when
`self._delivery_failed` is set**, else `_typed` exactly as today.

**Gate on the latch, not on a value comparison — and confine this to the failure
path.** `_emit()` has two early returns before delivery: the `_delivery_failed`
latch check, and the `output.max_chars` cap. Accumulating "before the latch
check" positionally would land the accumulation before the `max_chars` cap too,
so an utterance capped by `max_chars` would put the *full uncapped* transcript on
the clipboard. That is a behavior change nobody asked for: `max_chars` is an
explicit, user-configured **output** cap, the clipboard is output, and overriding
it via the clipboard is a policy call the user has not made. AC-2 is deliberately
scoped to "after a mid-utterance delivery failure" — nothing here licenses a
`max_chars` change. For the same reason, do **not** gate the `_finish()` copy on
"`_transcript` is non-empty and differs from `_typed`": that condition is also
true in the `max_chars` case and would capture it as a silent side effect. Gate
on `self._delivery_failed` explicitly.

Note that **both choices pass the existing suite** —
`test_max_chars_stops_typing_without_truncating_delta` asserts on `typed`/`pasted`
and never on the clipboard — so this fork is unobserved by the tests and must be
decided deliberately rather than discovered. (Fork identified by the FTHR-020
brooder and resolved with the orchestrator before implementation; recorded here so
it does not depend on conversation memory.)

`_finish()`'s existing copy is gated `if self._typed and ...`. Widen that gate so
a non-empty transcript is still copied when `_typed` is empty: if the *first*
delta fails, `_typed` is `""` and today nothing is copied at all — the worst case
of the very bug this feather closes (the utterance vanishes from cursor and
clipboard both). This is inside AC-2 and needs its own test; it is a distinct code
path from the mid-utterance failure case.

Note the two attributes answer different questions and both are needed:
`_typed` = "what reached the cursor" (invariant, return value); the new
accumulator = "what the user said" (clipboard fallback). Do not attempt to
re-derive the transcript by reformatting `self._transcriber.committed_words` at
`_finish()` time unless the accumulator proves unworkable — a second formatting
pass risks diverging from the incrementally-fed `HeuristicFormatter` output
(spacing/capitalisation/paragraph state is path-dependent), which would put
different text on the clipboard than was pasted.

**Do not "fix" the underlying hazard by loosening `ClipboardManager.copy()`'s
return.** `copy()` returns `True` only if both the clipboard and primary-selection
writes succeed. That strict return does not *cause* the desync — a partial
`wl-copy` failure desyncs the two selections whatever it returns — it is the only
thing that makes the desync *detectable* to `_emit()`. Loosening it would delete
the signal and leave the bug, with every test still passing.

## Tests
- `test_live.py::test_finish_copies_full_transcript_after_delivery_failure` — the
  central test. Force `clipboard.copy()` to return `False` on a mid-utterance
  delta (mirroring the setup in FTHR-017's
  `test_failed_copy_skips_paste_and_stops_at_prefix`), run to `_finish()`, and
  assert the last `clipboard.copy()` call carries the **full** transcript
  ("One two three"), not the delivered prefix ("One").
- `test_live.py::test_delivery_failure_still_stops_pasting_at_prefix` — pins
  FTHR-017's latch against regression by this feather: after the same forced
  failure, no `paste()` fires for the failed delta or any later one, and the
  delivered text remains a prefix of the final transcript. This must keep passing
  unchanged in substance.
- `test_live.py::test_first_delta_failure_still_copies_full_transcript` — the
  empty-`_typed` case. Force `clipboard.copy()` to fail on the **first** delta, so
  `_typed` stays `""`, and assert the full transcript still reaches the clipboard.
  Distinct code path from the mid-utterance test above (it exercises the widened
  `if self._typed` gate in `_finish()`), and the worst case of the bug this
  feather closes: today nothing is copied at all and the utterance vanishes.
- `test_live.py::test_max_chars_clipboard_unchanged` — pins the fork decision.
  With deliveries succeeding but `output.max_chars` capping the utterance, assert
  the clipboard still carries the **capped** text (`_typed`), not the full
  uncapped transcript — i.e. the accumulator does not leak into the `max_chars`
  path. The existing `test_max_chars_stops_typing_without_truncating_delta` never
  asserts on the clipboard, which is why this fork is otherwise unobserved.
- `test_live.py::test_finish_recopies_full_transcript` (existing, FTHR-017) — run
  unmodified to confirm the happy path still copies the full transcript exactly
  once and is not double-copied or altered.
- `test_live.py::test_prefix_invariant_paste_mode` (existing, FTHR-017) — run
  unmodified; the invariant is untouched by this feather.
- `test_formatter.py` (existing suite) — run unmodified; no formatter change.
- Implementation order is fixed: (1) write the tests above; (2) run them against
  unchanged code and confirm they FAIL for the expected reason (the first test
  will show the clipboard holding the delivered prefix instead of the full
  transcript); (3) implement until they pass.

## Acceptance Criteria
- [ ] AC-1: The tests listed above were observed failing before implementation and pass after.
- [ ] AC-2: After a mid-utterance delivery failure, `_finish()` copies the full formatted transcript to the clipboard, not the delivered prefix — so the undelivered remainder is recoverable by a manual paste. Extends PLM-010 FC-3/AC-3's "clipboard is the independent fallback" guarantee to the failure path.
- [ ] AC-3: FTHR-017's `_delivery_failed` latch is preserved: after a failed delta, no later delta is pasted, and the delivered text remains a prefix of the final transcript — satisfies PLM-010 AC-8, unweakened.
- [ ] AC-4: `self._typed` still means "text actually delivered to the cursor" and remains `_finish()`'s return value — the clipboard change does not conflate delivered text with the transcript.
- [ ] AC-5: The happy path is unchanged: with all deliveries succeeding, `_finish()` copies the full transcript exactly once, as today (existing `test_finish_recopies_full_transcript` passes unmodified).
- [ ] AC-6: `ClipboardManager.copy()`'s strict return is unchanged and `output/clipboard.py` is untouched.
- [ ] AC-7: `HeuristicFormatter`'s existing test suite passes unmodified — no formatting-rule change.
- [ ] AC-8: The full unit test suite (`.venv/bin/pytest -m "not integration"`) passes with no regressions.
- [ ] AC-9: The `output.max_chars` path is unchanged: a capped utterance still puts the capped text on the clipboard, not the full uncapped transcript. The clipboard change is gated on `self._delivery_failed`, not on a `_transcript`/`_typed` value comparison. (Fork resolved deliberately — both choices pass the pre-existing suite.)
- [ ] AC-10: A first-delta delivery failure (`_typed == ""`) still copies the full transcript to the clipboard — `_finish()`'s `if self._typed` gate is widened so the utterance is not lost entirely.
