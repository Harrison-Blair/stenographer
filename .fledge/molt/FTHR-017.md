# FTHR-017 evidence

Branch selection: `.fledge/molt/FTHR-015.md` records
`RESULT: 3/3 PASS — build universal chord (PLM-009 FC-1/FC-2)` under its AC-2,
which explicitly selects "the **per-word delta-firing** branch for FTHR-017
(PLM-010 FC-4/AC-4)". **Per-word branch built; the single-shot deferral branch
NOT built**, per the plumage's pre-committed binary rule. No config switch
between the two shapes exists (the spec's Approach forbids it).

## AC-1

The tests named in the feather's Tests section (per-word branch + the
branch-independent ones, plus the partial-clipboard hazard test the Approach
requires), observed FAILING against unchanged `src/`, then passing after
implementation.

### Pre-implementation run (verbatim, captured at the time)

`src/` confirmed unmodified at capture time:

```
$ git diff --stat -- src/
=== src/ is UNCHANGED (no diff above) ===
$ .venv/bin/pytest -m "not integration" -q \
    tests/test_live.py::test_emit_uses_paste_not_type_text \
    tests/test_live.py::test_delta_pastes_fire_per_committed_word \
    tests/test_live.py::test_failed_copy_skips_paste_and_stops_at_prefix \
    tests/test_live.py::test_prefix_invariant_paste_mode \
    tests/test_session.py::test_streaming_enabled_with_paste_injection
FAILED tests/test_live.py::test_emit_uses_paste_not_type_text - AssertionErro...
FAILED tests/test_live.py::test_delta_pastes_fire_per_committed_word - Assert...
FAILED tests/test_live.py::test_failed_copy_skips_paste_and_stops_at_prefix
FAILED tests/test_live.py::test_prefix_invariant_paste_mode - AssertionError:...
FAILED tests/test_session.py::test_streaming_enabled_with_paste_injection - a...
5 failed in 0.23s
```

Failure reasons — each is the expected one:

```
E       AssertionError: assert ['Hello', ' world '] == []
E         Left contains 2 more items, first extra item: 'Hello'
E       AssertionError: assert [] == ['One']
E         Right contains one more item: 'One'
E       AssertionError: assert [] == ['One']
E         Right contains one more item: 'One'
E       AssertionError: assert '' == 'It works now...nAnd I agree '
E         - It works now.
E         -
E         - And I agree
E       assert False is True
E        +  where False = <stenographer.session.Session object at 0x7f3832356ba0>._streaming
```

Mapping of each failure to the behaviour it pins:

- `test_emit_uses_paste_not_type_text` — `_emit()` still routes through
  `type_text()`, so `injector.typed` holds the deltas that should have been
  pasted (`['Hello', ' world '] == []`).
- `test_delta_pastes_fire_per_committed_word` — no delta is pasted at all
  (`[] == ['One']`); nothing reaches the clipboard/paste seam mid-utterance.
- `test_failed_copy_skips_paste_and_stops_at_prefix` — same seam absent, so
  the hazard guard does not exist to be exercised (`[] == ['One']`).
- `test_prefix_invariant_paste_mode` — delivered text reconstructed from pasted
  payloads is empty; nothing is delivered by paste (`'' == 'It works now...'`).
- `test_streaming_enabled_with_paste_injection` — `Session._streaming` still
  requires `injection_method == "text"`, so paste mode does not stream.

### Post-implementation run

```
$ .venv/bin/pytest -m "not integration" -q \
    tests/test_live.py::test_emit_uses_paste_not_type_text \
    tests/test_live.py::test_delta_pastes_fire_per_committed_word \
    tests/test_live.py::test_failed_copy_skips_paste_and_stops_at_prefix \
    tests/test_live.py::test_prefix_invariant_paste_mode \
    tests/test_session.py::test_streaming_enabled_with_paste_injection \
    tests/test_live.py::test_finish_recopies_full_transcript
......                                                                   [100%]
6 passed in 0.15s
```

### Mutation check (the repo's test-verification rule)

A test only counts if it fails when the behaviour breaks. The hazard guard is
the novel logic here, so it was mutation-tested two ways against the shipped
test:

```
### MUTATION 1: paste unconditionally (ignore copy() result) ###
E       AssertionError: assert ['One', ' two', ' three'] == ['One']

### MUTATION 2: drop the latch (skip failed delta, keep delivering) ###
E       AssertionError: assert ['One', ' three'] == ['One']

### RESTORED ###
485 passed, 4 deselected in 15.52s
```

Mutation 2 is the important one: it reproduces the exact silent corruption the
spec's Approach describes — delivered text `"One three"`, a **gap** where the
dropped delta belonged, which is not a prefix of the transcript `"One two
three "`. This is why the failure is latched for the rest of the utterance
rather than merely skipping the one delta.

### Regression guards — passed BEFORE and after (NOT failing-first)

Stated plainly rather than implied: `test_live.py::test_finish_recopies_full_transcript`
(AC-4) passes against unchanged `src/` as well as after. It pins pre-existing
`_finish()` behaviour that this feather must *preserve*, not introduce, so it
was never expected to fail first:

```
$ .venv/bin/pytest -m "not integration" -q tests/test_live.py::test_finish_recopies_full_transcript
.                                                                        [100%]
1 passed in 0.13s
```

Likewise `test_formatter.py` (AC-7) passes unmodified before and after.

## AC-2

`LiveStreamer._emit()` (`src/stenographer/live.py`) no longer references
`type_text` at all; it delivers via `self._clipboard.copy(text)` then
`self._injector.paste()`. The whole live path is free of the typing seam:

```
$ grep -rn "type_text" src/stenographer/live.py
(no matches)
```

Pinned by `test_emit_uses_paste_not_type_text`, which drives two interim steps
plus `_finish()` and asserts `injector.typed == []` (the fake still *has* a
recording `type_text()`, so a regression would show up as a non-empty list
rather than an AttributeError) while `clipboard.copy` was called and
`injector.pasted` is non-empty.

## AC-3

`session.py:155` now reads:

```python
        # Live word-level streaming pastes each committed delta as it is
        # confirmed; text mode assembles the utterance and types it.
        self._streaming = bool(cfg.streaming.enabled and cfg.output.injection_method == "paste")
```

Pinned by `test_session.py::test_streaming_enabled_with_paste_injection`
(`_streaming is True` under `"paste"`), observed failing first (see AC-1).

**Pre-existing test inverted — called out explicitly, not slipped in.** The old
`test_session.py::test_streaming_not_active_in_paste_mode` asserted
`session._streaming is False` for `injection_method == "paste"` — the exact
inverse of AC-3. It pinned the routing this feather is commissioned to flip, so
it could not survive unchanged. It was **replaced by two tests**, keeping both
directions of the routing pinned rather than dropping coverage:

- `test_streaming_enabled_with_paste_injection` — paste mode streams (the new
  behaviour, AC-3).
- `test_streaming_not_active_in_text_mode` — text mode does not stream (the
  mirror image of the old assertion, preserving its intent on the other arm).

Consequentially, `_streaming_cfg()` (test_session.py:1143) flipped from
`"text"` to `"paste"`, since it feeds six other live-streaming wiring tests
(`test_streaming_recording_start_wires_on_partial_and_enqueues_live_item`,
`test_streaming_recording_stop_signals_final_not_enqueue`,
`test_cancel_all_signals_live_streamer_abort`, and three more) that must now
construct a streaming session under the new routing. Those tests' assertions
are untouched. `_paste_chunk_cfg()` sets `streaming.enabled = False`, so the
non-streaming chunk-aggregation pipeline is unaffected by the flip (verified:
its tests pass unchanged).

## AC-4

`_finish()` is behaviourally unchanged — the full-transcript re-copy at
`live.py` still runs after `_emit()`:

```python
        self._emit(self._formatter.feed(delta) + self._formatter.finalize())
        if self._typed and self._cfg.clipboard.enabled and self._caps.has_wl_copy:
            try:
                self._clipboard.copy(self._typed)
```

Because `_emit()` now copies each delta too, the re-copy is the **last** copy of
the utterance, so the clipboard ends holding the whole transcript — the
independent fallback. Pinned by `test_finish_recopies_full_transcript`
(`clipboard.copy.call_args_list[-1] == call("Hello world again ")`) and by
`test_partials_commit_and_type_deltas_then_final_flushes`, which asserts the
full ordered call list `[call("Hello"), call(" world again "), call("Hello
world again ")]` — delta copies followed by the re-copy.

Note this test passes before and after (see AC-1's regression-guard section); it
guards preserved behaviour rather than new behaviour.

## AC-5

FTHR-015's `RESULT:` was 3/3 PASS, so this criterion is the live one. Each
committed delta fires its own `copy()`+`paste()` during the utterance, from
`_emit()`, which is called from `_step()` per commit — no deferral.

Pinned by `test_delta_pastes_fire_per_committed_word`, which asserts the pair
has already fired *mid-utterance* (after two `_step()`s, before any further step
or `_finish()`): `injector.pasted == ["One"]` and `clipboard.copy.call_args_list
== [call("One")]`; then after two more steps, `["One", " two"]` — a second
independent pair.

## AC-6

Vacuous — its condition ("If FTHR-015's `RESULT:` was the fallback") is false.
The single-shot deferral shape was NOT built, deliberately, and neither shape is
selectable at runtime (the spec's Approach forbids building both behind a
config switch). Verified absent — the single-shot-only test named by the spec
does not exist, and nothing defers delivery to `_finish()`:

```
$ grep -rn "test_no_paste_until_finish" tests/
(no matches)
```

`_emit()` has exactly one delivery shape: copy+paste per delta, at commit time.

## AC-7

`HeuristicFormatter` is reused unchanged through its existing
`feed()`/`finalize()` API — the formatter still sees **every** delta via
`self._formatter.feed(delta)` in `_step()`/`_finish()` (unchanged call sites),
so spacing/capitalisation/paragraph-break state stays correct. No formatting
logic was touched:

```
$ git diff --stat -- src/stenographer/output/formatter.py tests/test_formatter.py
(no changes)

$ .venv/bin/pytest -m "not integration" -q tests/test_formatter.py
....................                                                     [100%]
20 passed in 0.13s
```

Also untouched, per the feather's scope: `asr/streaming.py`'s LocalAgreement-N
algorithm and the non-streaming chunk-aggregation pipeline.

```
$ git diff --name-only -- src/
src/stenographer/live.py
src/stenographer/session.py
```

## AC-8

`test_live.py::test_prefix_invariant_paste_mode` passes. It is the renamed,
paste-seam-reseated form of the existing property test (the spec cites it as
`test_prefix_invariant_M6`, a name that does not exist in the tree; the real one
was `test_prefix_invariant_deltas_reconstruct_final_transcript`).

**Renamed, not deleted, and strictly strengthened.** The old test reconstructed
delivered text from `type_text()` arguments — a seam the live path no longer
uses, so it could not survive as-is. Rather than delete it and add a separate
analogue (which would have duplicated its script verbatim), it was renamed to
the spec-mandated `test_prefix_invariant_paste_mode` and re-seated on the paste
seam. Its script, its config, and both assertion blocks are otherwise
unchanged, so its lineage is intact. The reconstruction is now *stronger* than
before: `injector.pasted` records the clipboard payload actually in place at
each `paste()` call, so it measures what the chord really delivers, not merely
what was handed to the injector.

It asserts, across tail revisions, punctuation churn, a sentence-boundary trim
and a paragraph-length pause: (a) every intermediate delivered concatenation is
a prefix of the final text; (b) the delivered deltas reconstruct exactly the
batch-formatted transcript (`fresh.format_batch(committed_words)`) — no
duplicated, missing or reordered words.

The invariant is additionally pinned under failure by
`test_failed_copy_skips_paste_and_stops_at_prefix` (AC-1, incl. its mutation
check) — the partial-clipboard hazard from the spec's Approach.

### Why `ClipboardManager.copy()`'s strict return must stay

Recorded at the orchestrator's direction, from the FTHR-016 brooder that built
the mechanism this feather calls. It corrects a misreading the spec's Approach
text invites, and it is the reason `test_failed_copy_skips_paste_and_stops_at_prefix`
exists. **The strict return does not CAUSE the hazard — it is the only thing
that makes the hazard DETECTABLE.**

A partial `wl-copy` failure desyncs the clipboard from the primary selection
*regardless of what `copy()` returns*. The desync is in the world, not in the
return value. `copy()` returning `True` only when both `wl-copy` calls succeed
is what surfaces that desync to `_emit()`, which is the entire basis of the
guard below.

The tempting "fix" is therefore exactly wrong: loosening the return (e.g.
returning `True` when only the regular clipboard succeeded) would **destroy the
signal while leaving the desync in place**. That is strictly worse than doing
nothing, because the prefix invariant would then break with nothing able to
observe it — silently wrong text, no failing test, no error.

Consequences for anyone editing this code:

- Do not loosen `copy()`'s return to "fix" a delivery gap. The gap is the
  symptom; the strict return is the smoke alarm, not the fire.
- `src/stenographer/output/clipboard.py` is **out of scope** for this feather
  and was not touched (`git diff --name-only -- src/` lists only `live.py` and
  `session.py`). Anyone wanting to change `copy()`'s contract should stop and
  escalate rather than edit it in passing.
- `test_failed_copy_skips_paste_and_stops_at_prefix` is what pins this. Without
  it, someone loosens the return, every remaining test still passes, and the
  invariant rots silently. Its mutation check (AC-1) shows both failure shapes
  it catches.

### The hazard guard, as shipped

`_emit()` pastes only on a fully successful `copy()`, and latches output off for
the rest of the utterance on any delivery failure:

- **Why not paste on `copy() == False`:** `ClipboardManager.copy()` populates
  the clipboard *and* the primary selection, returning `False` if either failed.
  A `False` can therefore mean the selections disagree (clipboard holds this
  delta, primary still holds the previous one). kitty pastes from PRIMARY
  (`paste_from_selection`, per FTHR-015), so pasting then could deliver a stale,
  out-of-order word — silently wrong text, not a visible error.
- **Why latch rather than skip-and-continue:** a later delta pasted after a
  dropped one leaves the delivered text with a hole, which is no longer a prefix
  of the transcript. Mutation 2 above demonstrates exactly this (`"One three"`).
  Stopping cleanly at a prefix boundary is correct; resynchronising by guesswork
  is not, and none is attempted.
- The failure surface is real, not theoretical: `copy()` is now two `wl-copy`
  subprocess calls where the replaced `type_text()` was one.
- `self._typed` is unchanged on failure (the existing truthy-return
  bookkeeping), so `_finish()`'s re-copy still publishes exactly what was
  delivered — the clipboard fallback survives a latched utterance.
- The `max_chars` early-return guard is retained unchanged.

## AC-9

Full unit suite, no regressions. Pre-change baseline on this worktree was **480
passed** (measured by stashing the change and re-running), and the tree now runs
**485** — exactly +5, accounted for as: 4 new `test_live.py` tests, plus a net
+1 in `test_session.py` (one inverted test replaced by two). The prefix test was
renamed (net 0). No test was skipped, weakened in a way that unpins behaviour,
or lost.

```
$ git stash -q && .venv/bin/pytest -m "not integration" -q   # baseline
480 passed, 4 deselected in 15.47s
$ git stash pop -q

$ .venv/bin/pytest -m "not integration" -q
485 passed, 4 deselected in 15.75s

$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/ruff format --check .
55 files already formatted
```

Environment note: run from a worktree-local `.venv` created inside
`.fledge/burrows/FTHR-017` (`python3 -m venv .venv && .venv/bin/pip install -e
".[dev,build]"`), not the main checkout's venv — that one is an editable install
pointing at the main checkout's `src/` and would have tested the wrong code.
Confirmed with `stenographer.__file__` →
`/home/penguin/source/stenographer/.fledge/burrows/FTHR-017/src/stenographer/__init__.py`.

## Note for downstream work — not in this feather's scope

The three-pipeline routing in `.fledge/nest/architecture.md` and the `live.py`
description in `CLAUDE.md` both still say streaming is `text`-mode only, which
this feather inverts. Nest docs are forager-generated and `CLAUDE.md` is outside
this feather's Affected Modules, so neither was edited here. Flagged so the
staleness is a recorded decision rather than an oversight.
