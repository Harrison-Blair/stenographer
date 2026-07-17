# FTHR-020 — Preserve full transcript on clipboard when delta delivery fails

Worktree: `.fledge/burrows/FTHR-020` on `feather/FTHR-020-preserve-full-transcript` (cut from `dev`).
Venv: worktree-local, verified importing the worktree's own source **before any test was run**:

```
$ .venv/bin/python -c "import stenographer; print(stenographer.__file__)"
/home/penguin/source/stenographer/.fledge/burrows/FTHR-020/src/stenographer/__init__.py
```

## Change summary

`src/stenographer/live.py` only (23 insertions, 3 deletions):

1. `__init__`: added `self._transcript = ""` beside `self._typed`, commented to record that they
   answer different questions and diverge exactly when the latch engages.
2. `_emit()`: `if not text or self._delivery_failed: return` split so the accumulation
   (`self._transcript += text`) happens after the empty-text guard but **before** the latch
   check — it keeps growing after output stops, which is the point. The latch's own early
   return, the `max_chars` cap, and the delivery logic are otherwise byte-for-byte unchanged.
3. `_finish()`: the clipboard re-copy now selects
   `self._transcript if self._delivery_failed else self._typed`, and its gate widened from
   `if self._typed` to `if text` so a first-delta failure (`_typed == ""`) still copies.
   `_finish()` still returns `self._typed`.

## AC-1 — tests observed failing before implementation, passing after

Implementation order was as the spec fixes it: tests first, run against unchanged source,
failure captured verbatim at capture time, then implement.

### Pre-implementation — mid-utterance failure (source UNCHANGED)

```
$ .venv/bin/pytest tests/test_live.py -m "not integration" \
    -k "delivery_failure or full_transcript_after_delivery_failure"

__________ test_finish_copies_full_transcript_after_delivery_failure ___________
        typed = streamer._finish(_speech(2.0))

        # The delivered text still stops at the prefix (that is FTHR-017's latch,
        # and it is correct) ...
        assert typed == "One"
        assert injector.pasted == ["One"]
        # ... but the clipboard now holds everything the user actually said, so
        # the undelivered remainder is recoverable with a manual paste.
>       assert clipboard.copy.call_args_list[-1] == call("One two three ")
E       AssertionError: assert call('One') == call('One two three ')
E
E         Use -v to get more diff

tests/test_live.py:696: AssertionError
------------------------------ Captured log call -------------------------------
WARNING  stenographer.live:live.py:259 live: delta delivery failed; output stopped at 3 chars to keep
delivered text a prefix of the transcript
=========================== short test summary info ============================
FAILED tests/test_live.py::test_finish_copies_full_transcript_after_delivery_failure
================== 1 failed, 1 passed, 28 deselected in 0.18s ==================
```

Failing for exactly the reason the spec predicts: the clipboard's last payload is the
**delivered prefix** `'One'`, not the full transcript — "two three" lost. The captured warning
(`output stopped at 3 chars`) confirms the latch really engaged, so the test exercised the true
failure path rather than reaching a mismatch some other way.

### Pre-implementation — AC-9 / AC-10 tests (source re-reverted to unchanged)

The AC-9/AC-10 tests were added after the orchestrator resolved the `max_chars` fork (see AC-9).
The implementation already existed at that point, so it was **parked** (`live.py` reverted to its
unchanged state, verified with `git diff --quiet`) and the new tests were run against unchanged
source — tests written after an implementation prove nothing otherwise.

```
$ git checkout src/stenographer/live.py && git diff --quiet src/stenographer/live.py
live.py reverted to unchanged (pre-FTHR-020) state

$ .venv/bin/pytest tests/test_live.py -m "not integration" \
    -k "first_delta_failure or max_chars_clipboard"

        # Nothing ever reached the cursor ...
        assert typed == ""
        assert injector.pasted == []
        # ... so the clipboard is the only surviving copy of the utterance. It
        # must hold all of it.
>       assert clipboard.copy.call_args_list[-1] == call("One two ")
E       AssertionError: assert call('One') == call('One two ')
E
E         Use -v to get more diff

tests/test_live.py:758: AssertionError
------------------------------ Captured log call -------------------------------
WARNING  stenographer.live:live.py:259 live: delta delivery failed; output stopped at 0 chars to keep
delivered text a prefix of the transcript
=========================== short test summary info ============================
FAILED tests/test_live.py::test_first_delta_failure_still_copies_full_transcript
================== 1 failed, 1 passed, 30 deselected in 0.17s ==================
```

`output stopped at 0 chars` confirms the empty-`_typed` path specifically. The last `copy()` call
is the *failed* `'One'` attempt — `_finish()`'s `if self._typed` gate skipped the re-copy
entirely, i.e. the utterance vanished from cursor and clipboard both. That is the worst case
AC-10 describes, reproduced.

### Honest note on the two `1 passed` lines above

Those are the two **regression pins** — `test_delivery_failure_still_stops_pasting_at_prefix`
(AC-3) and `test_max_chars_clipboard_unchanged` (AC-9). They pass pre-implementation **by
design, not by oversight**: a pin's job is to pass before and after and to fail only if this
feather breaks what it pins ("This must keep passing unchanged in substance"). A
pre-implementation pass is no evidence of falsifiability on its own, so each is instead
demonstrated by mutation under AC-3 and AC-9 below.

### Post-implementation

```
$ .venv/bin/pytest tests/test_live.py -m "not integration" \
    -k "delivery_failure or full_transcript_after_delivery_failure or first_delta_failure or max_chars_clipboard"
tests/test_live.py ....                                                  [100%]
======================= 4 passed, 28 deselected in 0.14s =======================
```

## AC-2 — full transcript on the clipboard after a mid-utterance failure

`test_finish_copies_full_transcript_after_delivery_failure` (new). Forces `clipboard.copy()` to
return `False` on the delta carrying " two", mirroring FTHR-017's
`test_failed_copy_skips_paste_and_stops_at_prefix` setup. Asserts the last `copy()` carries
`"One two three "` — the full transcript — while the cursor still holds only `"One"`. The
remainder is therefore recoverable with a manual paste. Failing output pre-implementation and
passing output post-implementation both captured under AC-1.

`copy.side_effect = [True, False, True, True]`: only the second copy fails, so later copies would
succeed if they were attempted — nothing but the latch itself can be what stops delivery.

## AC-3 — FTHR-017's `_delivery_failed` latch preserved

`test_delivery_failure_still_stops_pasting_at_prefix` (new pin) asserts (a) no `paste()` fires for
the failed delta or any later one — including from `_finish()`, (b) the delivered text is still a
prefix of the final transcript reconstructed from `committed_words`, and (c) `_typed` is unchanged
in meaning.

**Mutation proof (a passing suite is not evidence the latch survived).** The FTHR-017 regression
was reproduced by deleting the latch's early return from `_emit()`:

```
=== latch mutated out; the pin MUST fail ===
>       assert injector.pasted == ["One"]
E       AssertionError: assert ['One', ' three', ' '] == ['One']
E         Left contains 2 more items, first extra item: ' three'
tests/test_live.py:712: AssertionError
=========================== short test summary info ============================
FAILED tests/test_live.py::test_delivery_failure_still_stops_pasting_at_prefix
======================= 1 failed, 29 deselected in 0.15s =======================
```

`['One', ' three', ' ']` is precisely the gap the latch exists to prevent — delivery resumed past
the dropped delta, so the delivered text is no longer a prefix. Full-suite sensitivity to that
same mutation, before and after this feather:

```
=== full suite WITH latch mutated out ===
FAILED tests/test_live.py::test_failed_copy_skips_paste_and_stops_at_prefix
FAILED tests/test_live.py::test_finish_copies_full_transcript_after_delivery_failure
FAILED tests/test_live.py::test_delivery_failure_still_stops_pasting_at_prefix
3 failed, 484 passed, 4 deselected in 15.52s
```

The latch's detector count goes from **1 of 485** (the FTHR-017 situation, where a `docs:`-labelled
commit deleted it with 484/485 still green) to **3 of 487**. Source restored from backup and the
suite re-verified green immediately after.

## AC-4 — `_typed` still means "text delivered to the cursor"

`_typed` is mutated in exactly one place, unchanged from FTHR-017: `self._typed += text` inside
`_emit()`'s `if delivered:` branch. `_finish()` still ends `return self._typed`, and `_run()`'s
abort paths still return it. The new `_transcript` is a separate attribute, written only by its own
`+=` and read only at the `_finish()` clipboard re-copy; it never feeds the injector, `max_chars`
accounting, or any return value. Pinned by
`test_delivery_failure_still_stops_pasting_at_prefix` assertion (c) (`typed == "One"` and
`streamer._typed == "One"` after a latched utterance whose transcript is `"One two three "` — the
two provably diverge without conflating).

## AC-5 — happy path unchanged

`test_finish_recopies_full_transcript` (existing, FTHR-017) passes **unmodified** — see AC-7's run.
On the happy path `_delivery_failed` is never set, so `_finish()` copies `self._typed` exactly as
before; `_typed` already *is* the full transcript there. No double-copy: the copy site is still a
single call.

## AC-6 — `output/clipboard.py` untouched

```
$ git diff dev --exit-code -- src/stenographer/output/clipboard.py && echo UNTOUCHED
UNTOUCHED
```

`ClipboardManager.copy()`'s strict return is unchanged. Per the spec, that strictness is not the
*cause* of the desync — a partial `wl-copy` failure desyncs the selections whatever it returns —
it is the only thing that makes the desync detectable to `_emit()`. It was deliberately not
touched.

## AC-7 — formatter untouched, its suite passes unmodified

```
$ git diff dev --exit-code -- src/stenographer/output/formatter.py tests/test_formatter.py && echo UNTOUCHED
UNTOUCHED

$ .venv/bin/pytest tests/test_formatter.py \
    tests/test_live.py::test_finish_recopies_full_transcript \
    tests/test_live.py::test_prefix_invariant_paste_mode \
    tests/test_live.py::test_failed_copy_skips_paste_and_stops_at_prefix \
    tests/test_live.py::test_max_chars_stops_typing_without_truncating_delta -m "not integration" -q
........................                                                 [100%]
24 passed in 0.17s
```

The spec's warning was heeded: the transcript is accumulated from the same
`self._formatter.feed(delta)` output that feeds `_emit()`, never re-derived by reformatting
`committed_words`. A second formatting pass over path-dependent `HeuristicFormatter` state could
diverge from the incrementally-fed output and put *different text* on the clipboard than was
pasted.

## AC-8 — full unit suite green, no regressions

```
$ .venv/bin/pytest -m "not integration" -q
489 passed, 4 deselected in 15.59s
```

487 on `dev` at the branch point + 2 new tests in the first commit + 2 new tests for AC-9/AC-10 =
489, with zero pre-existing tests modified or deleted. Lint clean:

```
$ .venv/bin/ruff check . && .venv/bin/ruff format --check .
All checks passed!
55 files already formatted
```

## AC-9 — `output.max_chars` path unchanged; gated on the latch, not a value comparison

The fork: `_emit()` has **two** early returns before delivery (the latch check *and* the
`max_chars` cap), so accumulating "before the latch check" positionally lands the accumulation
before the `max_chars` cap too — a capped utterance would then put the full uncapped transcript
on the clipboard. Identified before implementation and escalated rather than guessed, because
**both choices pass the pre-existing suite**: `test_max_chars_stops_typing_without_truncating_delta`
asserts only on `typed`/`pasted`, never on the clipboard. Resolved with the orchestrator and
recorded in the spec body (`1d43eea`), which this branch merges.

Implemented as resolved: `_finish()` selects
`self._transcript if self._delivery_failed else self._typed` — gated on the latch explicitly.
The accumulation sits before the latch check (so it keeps growing once output stops) but is
*used* only on the failure path, so `max_chars` behavior is untouched.

`test_max_chars_clipboard_unchanged` (new pin) asserts a capped utterance still copies `"Hello"`,
not `"Hello overflowing "`. **Mutation proof** — implementing the spec's explicitly rejected
alternative (`_transcript if _transcript and _transcript != _typed else _typed`):

```
=== gate mutated to the REJECTED value-comparison form; AC-9 pin MUST fail ===
>       assert clipboard.copy.call_args_list[-1] == call("Hello")
E       AssertionError: assert call('Hello overflowing ') == call('Hello')
FAILED tests/test_live.py::test_max_chars_clipboard_unchanged
```

The rejected form leaks the full uncapped transcript onto the clipboard and the pin catches it —
confirming both that the fork was real and that this test observes it. Source restored; suite
re-verified at 489 passed.

## AC-10 — first-delta failure (`_typed == ""`) still copies the full transcript

`test_first_delta_failure_still_copies_full_transcript` (new). Forces `copy()` to fail on the
**first** delta, so `_typed` stays `""` and `injector.pasted == []` — nothing reached the cursor,
making the clipboard the only surviving copy of the utterance. Asserts the last `copy()` carries
`"One two "`. Requires the widened gate (`if text` rather than `if self._typed`); pre-implementation
failure captured under AC-1 showing the old gate skipping the copy entirely.
