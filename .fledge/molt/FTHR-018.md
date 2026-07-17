# FTHR-018: Measure per-delta paste round-trip latency

Worktree: `.fledge/burrows/FTHR-018` on `feather/FTHR-018-measure-paste-latency` (cut from `dev`).
All commands run with the worktree-local venv (`.venv/bin/...`), which resolves
`stenographer` to this worktree's `src/` (verified: `pkg:
/home/penguin/source/stenographer/.fledge/burrows/FTHR-018/src/stenographer/__init__.py`).

**Oversight note (`oversight: during`).** This feather's test fires real
Shift+Insert keystrokes via `wtype` into whatever window has focus on the
user's live desktop, and mutates the real clipboard. A git worktree does not
isolate that — `wtype` talks to the real compositor. The brooder therefore
never ran the measurement. Every run the brooder executed was a
*skipped-without-env-var* run. **The measured numbers below come from the
user's own attended run on their hardware, relayed verbatim via the
orchestrator; the brooder simulated, mocked, and estimated nothing.**

This branch also merged `dev` (commit 8d6d5df) to pick up FTHR-021, the P0
clipboard-hang fix that this feather's first measurement run exposed. The
numbers recorded here are therefore post-fix and represent a functioning
paste path.

## AC-1

The test was observed absent (failing at collection) before implementation, and
collected after.

**Before implementation** — `.venv/bin/pytest "tests/test_inject.py::test_paste_round_trip_latency"`:

```
ERROR: not found: /home/penguin/source/stenographer/.fledge/burrows/FTHR-018/tests/test_inject.py::test_paste_round_trip_latency
(no match in any of [<Module test_inject.py>])

============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/penguin/source/stenographer/.fledge/burrows/FTHR-018
configfile: pyproject.toml
collected 0 items

============================ no tests ran in 0.02s =============================
```

This is the expected pre-implementation failure reason: the test did not exist,
so pytest could not match the node ID.

**After implementation** — `.venv/bin/pytest "tests/test_inject.py::test_paste_round_trip_latency" -v -rs`:

```
collecting ... collected 1 item

tests/test_inject.py::test_paste_round_trip_latency SKIPPED (set STE...) [100%]

=========================== short test summary info ============================
SKIPPED [1] tests/test_inject.py:321: set STENOGRAPHER_INTEGRATION=1 to run integration tests
============================== 1 skipped in 0.04s ==============================
```

**Then it failed for a second, better reason.** Its first real-hardware
execution (AC-2, run 0, branch state `eed9370`) failed on iteration 1 —
`copy()` returned `False` after a 10s hang, the FTHR-021 P0 — and produced no
measurement at all. So this test has been observed failing twice, for two
distinct and legitimate reasons: first because it did not exist, then because
the code beneath it was genuinely broken. The second failure is the more
valuable of the two.

**Passing run at current HEAD** — the user's attended run at commit 89b9faf
(AC-2, run 2; full log there):

```
tests/test_inject.py::test_paste_round_trip_latency  streaming
...
INFO     ... paste round-trip latency over 10 iterations (delta=' streaming'): min=37.3 ms median=37.5 ms max=38.3 ms
PASSED

================================== 1 passed in 0.42s ===================================
```

### Status: AC-1 satisfied

Stated precisely, because an earlier revision of this document claimed it on
weaker grounds than it had:

- The failing runs are observed and real: the collection failure (test absent),
  and run 0's real failure (the FTHR-021 P0).
- Run 1 passed — but against commit **049888a**, and `tests/test_inject.py`
  changed at **89b9faf**. That pass could not carry AC-1 for the shipped code,
  and the unit suite could not stand in for it: the test is
  `integration`-marked, so a mistake in the teardown edit would not have been
  caught by `490 passed`.
- **Run 2 passed against 89b9faf — current HEAD.** That is the observation AC-1
  asks for, on the code actually being shipped.

The document claimed AC-1 prematurely once, on the strength of run 1 plus the
reasonable-but-unobserved inference that the teardown edit was harmless. The
skua caught it. Run 2 is what made the claim true rather than merely likely.

**Provenance.** The brooder executed the pre-implementation failing run and the
collected/skipped runs. The brooder executed **none** of the real-hardware runs
— runs 0, 1, and 2 are the user's, on their hardware, relayed by the
orchestrator, because `oversight: during` forbids the brooder from firing
`wtype` at the user's live desktop.

## AC-2

**Satisfied.** Runs 1 and 2 each produced a logged real measurement of the
delta round-trip on the user's hardware — min/median/max plus raw per-iteration
durations — which is what PLM-010 FC-7/AC-7 asks for. Run 2 is the one against
current HEAD.

Every real-hardware run was executed by the user, on their hardware, and
relayed by the orchestrator. Command (identical for all):

```sh
cd /home/penguin/source/stenographer/.fledge/burrows/FTHR-018
STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest tests/test_inject.py::test_paste_round_trip_latency -s --log-cli-level=INFO
```

Three runs are recorded below, in order. The narrative deliberately starts at
the **failing** run, not at the first passing one: this test's first real
execution found a P0, and that is the most useful thing this feather did.

| | branch state | result | wall-clock | measurement produced? |
|---|---|---|---|---|
| **Run 0** | `eed9370`, pre-`dev`-merge → **pre-FTHR-021** | **FAILED** | 20.05s | **No** — found the P0 |
| **Run 1** | `049888a`, post-FTHR-021, pre-teardown-fix | PASSED | 10.40s | Yes — min 37.3 / **med 37.4** / max 38.4 ms |
| **Run 2** | `89b9faf`, post-teardown-fix (**current HEAD**) | PASSED | **0.42s** | Yes — min 37.3 / **med 37.5** / max 38.3 ms |

The three are distinct and must not be conflated: only run 0 failed, and only
run 2 exercised the code at current HEAD. Runs 1 and 2 independently reproduce
the same measurement; run 2 is the one AC-1 rests on.

### Run 0 — first real-hardware attempt, pre-FTHR-021 (FAILED)

Branch state `eed9370`, before `dev` was merged in — so `clipboard.py` still
carried `capture_output=True` on `wl-copy`. User-executed, verbatim:

```
tests/test_inject.py::test_paste_round_trip_latency FAILED

=================================== FAILURES ===================================
_____________________ test_paste_round_trip_latency _____________________

        durations: list[float] = []
        for i in range(_LATENCY_ITERATIONS):
            start = time.monotonic()
>           assert clip.copy(_LATENCY_DELTA) is True
E           AssertionError: assert False is True
E            +  where False = copy(' streaming')
E            +    where copy = <stenographer.output.clipboard.ClipboardManager object at 0x7fd2c4578440>.copy

tests/test_inject.py:337: AssertionError
=========================== short test summary info ============================
FAILED tests/test_inject.py::test_paste_round_trip_latency - AssertionError: assert False is True
============================== 1 failed in 20.05s ==============================
```

It died on **iteration 1**: `copy()` never once succeeded, so **no latency was
measured at all**. Per the orchestrator's analysis, the 20.05s decomposes as
`_save_clipboard`'s 10s timeout plus `copy()`'s first `wl-copy` 10s timeout.

**Why this run matters more than the measurement.** It is the run that produced
FTHR-021 — a v1-era latent P0 (`capture_output=True` on `wl-copy` since
f20ee52) in which `copy()` hung 10s and then returned `False` **every time**,
meaning live streaming delivered nothing, the primary selection was never
populated, and every dictation stalled 10s. The feature had been dead since v1.

The whole suite was green throughout — 489 unit tests passing while `copy()`
could not complete a single call — because those tests mock `subprocess.run`,
and mocking `subprocess.run` mocks away the exact fork-and-hold-the-pipes
behaviour that was broken. **A mocked suite proves intent, not behaviour.** The
first time this code met a real `wl-copy`, it failed instantly and on iteration
1. That is what this feather's failing run bought, and it is worth more than the
number the feather was commissioned to produce.

*Provenance note:* this run happened in the orchestrator's session with the
user, before this branch had `dev` merged, so it exists nowhere in this
worktree's history. It was supplied by the orchestrator and is recorded here
verbatim so it survives outside a conversation.

### Run 1 — post-FTHR-021, pre-teardown-fix (commit 049888a)

Verbatim output as relayed by the orchestrator:

```
tests/test_inject.py::test_paste_round_trip_latency  streaming
-------------------------------- live log call ---------------------------------
INFO     tests.test_inject:test_inject.py:341 paste round-trip iteration 1/10: 38.4 ms
INFO     tests.test_inject:test_inject.py:341 paste round-trip iteration 2/10: 37.9 ms
INFO     tests.test_inject:test_inject.py:341 paste round-trip iteration 3/10: 37.9 ms
INFO     tests.test_inject:test_inject.py:341 paste round-trip iteration 4/10: 37.5 ms
INFO     tests.test_inject:test_inject.py:341 paste round-trip iteration 5/10: 37.3 ms
INFO     tests.test_inject:test_inject.py:341 paste round-trip iteration 6/10: 37.5 ms
INFO     tests.test_inject:test_inject.py:341 paste round-trip iteration 7/10: 37.3 ms
INFO     tests.test_inject:test_inject.py:341 paste round-trip iteration 8/10: 37.3 ms
INFO     tests.test_inject:test_inject.py:341 paste round-trip iteration 9/10: 37.3 ms
INFO     tests.test_inject:test_inject.py:341 paste round-trip iteration 10/10: 37.4 ms
INFO     tests.test_inject:test_inject.py:348 paste round-trip latency over 10 iterations (delta=' streaming'): min=37.3 ms median=37.4 ms max=38.4 ms
INFO     tests.test_inject:test_inject.py:357 paste round-trip raw durations (ms): [38.4, 37.9, 37.9, 37.5, 37.3, 37.5, 37.3, 37.3, 37.3, 37.4]
PASSED

================================= 1 passed in 10.40s ==================================
```

This is the real logged measurement PLM-010 FC-7/AC-7 asks for. The `10.40s`
wall-clock is teardown overhead, not measurement — see the finding under AC-4;
it does not affect the per-iteration numbers, which are timed individually
around `copy()` + `paste()` only.

### Run 2 — post-teardown-fix (commit 89b9faf, current HEAD) — PASSED

The passing run against the code actually being shipped. User-executed,
verbatim:

```
tests/test_inject.py::test_paste_round_trip_latency  streaming
-------------------------------- live log call ---------------------------------
INFO     tests.test_inject:test_inject.py:355 paste round-trip iteration 1/10: 38.3 ms
INFO     tests.test_inject:test_inject.py:355 paste round-trip iteration 2/10: 37.4 ms
INFO     tests.test_inject:test_inject.py:355 paste round-trip iteration 3/10: 38.0 ms
INFO     tests.test_inject:test_inject.py:355 paste round-trip iteration 4/10: 37.3 ms
INFO     tests.test_inject:test_inject.py:355 paste round-trip iteration 5/10: 37.3 ms
INFO     tests.test_inject:test_inject.py:355 paste round-trip iteration 6/10: 37.5 ms
INFO     tests.test_inject:test_inject.py:355 paste round-trip iteration 7/10: 37.4 ms
INFO     tests.test_inject:test_inject.py:355 paste round-trip iteration 8/10: 37.3 ms
INFO     tests.test_inject:test_inject.py:355 paste round-trip iteration 9/10: 37.5 ms
INFO     tests.test_inject:test_inject.py:355 paste round-trip iteration 10/10: 37.5 ms
INFO     tests.test_inject:test_inject.py:362 paste round-trip latency over 10 iterations (delta=' streaming'): min=37.3 ms median=37.5 ms max=38.3 ms
INFO     tests.test_inject:test_inject.py:371 paste round-trip raw durations (ms): [38.3, 37.4, 38.0, 37.3, 37.3, 37.5, 37.4, 37.3, 37.5, 37.5]
PASSED

================================== 1 passed in 0.42s ===================================
```

Two things this run establishes, both of which were open questions before it:

**1. AC-1 is satisfied for the code being shipped.** Run 1 passed against
049888a, but `tests/test_inject.py` changed at 89b9faf (teardown helpers and
their call sites), so no passing run existed for current HEAD — and the unit
suite could not close that gap, since this test is `integration`-marked and
skips there. Run 2 closes it by observation. The log's line numbers moved
(341→355), which is consistent with the helper edits and corroborates that this
ran against post-89b9faf code rather than a stale checkout.

**2. The teardown fix works, and the prediction became evidence.** Wall-clock
fell **10.40s → 0.42s**; the ten iterations sum to ~0.375s, so residual
overhead is ~45 ms and the ~10s `_restore_clipboard` timeout is gone. The
measured numbers held across the change (median 37.5 vs 37.4 ms, identical
37.3 ms floor, max 38.3 vs 38.4 ms).

That second point is worth stating precisely, because an earlier revision of
this document got it wrong. The claim "nothing in the measured path moved, so
the numbers stand" was, before run 2, a **prediction dressed as evidence** — it
was reasonable, and it turned out correct, but it had not been observed. Run 2
is what converted it. The distinction is the whole subject of run 0's lesson
below, and it applied to this document's own reasoning too.

## AC-3

No assertion in the test compares a measured duration against any constant. The
test's complete set of assertions:

```
assert clip.copy(_LATENCY_DELTA) is True
assert inj.paste() is True
```

Both assert call success only. `durations` is consumed exclusively by
`logger.info(...)` calls (`min`/`statistics.median`/`max` and the raw list); it
is never compared to a bound. The test therefore cannot fail because the
round-trip was slow — only because `wl-copy` or `wtype` itself failed. This
matches the user's explicit decision to decline a latency budget (PLM-010
FC-7/AC-7), so no threshold was invented.

## AC-4

### The measurement

One streamed delta's full paste round-trip — `ClipboardManager.copy()` (which
is 2× `wl-copy`: regular clipboard + primary selection) followed by
`Injector.paste()` (1× `wtype` Shift+Insert).

**Measured twice, independently, on two different commits:**

| | run 1 (049888a) | run 2 (89b9faf, HEAD) |
|---|---|---|
| min | 37.3 ms | **37.3 ms** |
| median | 37.4 ms | **37.5 ms** |
| max | 38.4 ms | **38.3 ms** |

Raw per-iteration durations (ms):

- Run 1: `[38.4, 37.9, 37.9, 37.5, 37.3, 37.5, 37.3, 37.3, 37.3, 37.4]`
- Run 2: `[38.3, 37.4, 38.0, 37.3, 37.3, 37.5, 37.4, 37.3, 37.5, 37.5]`

**Take ~37.5 ms as the figure of record** (run 2, current HEAD). The two runs
agree to 0.1 ms of median and share an identical 37.3 ms floor.

**Conditions.** User's hardware, Hyprland/Wayland, Python 3.14.6, run from the
FTHR-018 burrow with its worktree-local venv, `delta=' streaming'`, 10
iterations, post-FTHR-021. Measured with `time.monotonic()` around `copy()` +
`paste()` only.

**Scope of the claim.** This is ~37 ms of *cost to deliver one delta*, measured
per committed word. It is not end-to-end dictation latency: ASR decode time is
excluded entirely. Whether ~37 ms/word is acceptable is deliberately not
assessed here — the user declined a latency budget (PLM-010 FC-7/AC-7), so this
section records what the cost is and leaves the judgement to the reader.

**Observations about the distribution**, offered as fact rather than verdict:

- *Within* each run the spread is ~1 ms (37.3–38.4), with most iterations
  falling within 0.6 ms of each other.
- *Across* the two runs — different commits, minutes apart — the medians agree
  to 0.1 ms and the floor is identical at 37.3 ms.

A cost that tight, and that reproducible across runs, is characteristic of
fixed process-spawn overhead (three `subprocess.run` calls per delta) rather
than of anything varying with content, load, or run conditions. The two runs
agreeing is stronger evidence for that reading than either alone: it makes the
figure a property of the machine and the three spawns, not an artifact of one
run's circumstances.

The practical consequence for a future reader: this number is unlikely to
improve by tuning, and would move mainly by spawning fewer processes per delta.
Whether it *should* move is not assessed here — see the scope note above.

### Finding: the same clipboard-restore bug existed in three copies

Run 1 took **10.40s** wall-clock while the ten measured iterations sum
to ~0.37s. The missing ~10s was `_restore_clipboard` in this file — FTHR-021's
exact defect (`capture_output=True` on `wl-copy`, whose forked daemon inherits
and holds the pipes until the 10s timeout fires), in a third copy of the
helper. `contextlib.suppress` swallowed the `TimeoutExpired`, so the restore
landed and the test passed; the 10s was eaten silently in teardown.

That makes three independent copies of the same defect: `clipboard.py`
(FTHR-021, production), `test_clipboard.py`'s helper (FTHR-021), and this
file's helper (found here). Each was written and reviewed separately and each
carried the same bug. **The pattern was the problem, not any one instance** —
which is the strongest available argument that `capture_output=True` on a
daemonizing process is a trap worth naming rather than fixing case by case.

Note the escalation across the three: in `clipboard.py` it was a P0 that killed
the feature (run 0). In this file's helper it was invisible — `contextlib.suppress`
ate the exception, the test passed, and the only symptom was a wall-clock number
in a test whose entire job is reporting wall-clock numbers. The same defect is
fatal in one place and silent in another, which is precisely why the pattern
needs a name rather than three separate fixes.

Fixed in this branch, and **confirmed by run 2: 10.40s → 0.42s** (ten
iterations sum to ~0.375s, so ~45 ms of residual overhead remains and the ~10s
timeout is gone). Fixed to match `clipboard.py`'s shipped form
(`stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL`), with a comment
pointing at FTHR-021. `_save_clipboard` uses `wl-paste` and keeps
`capture_output=True`, which is correct and not the same case: `wl-paste` does
not daemonize, and its stdout is the data being read.

### Second fix: the primary selection was not being restored

Found while fixing the above. `copy()` writes **both** the regular clipboard
and the primary selection (FTHR-016's universal-chord behaviour), but the
save/restore here only covered the regular clipboard — so each run left
`" streaming"` sitting in the user's primary selection. `_save_clipboard` /
`_restore_clipboard` now take a `primary` flag and the test saves and restores
both. This is cleanup of the test's own mess, not scope creep: the test was
clobbering user state it had failed to preserve.

Neither fix touches the measured code path (`copy()` / `paste()`) — both affect
only teardown. That was the reasoning for expecting the numbers to survive the
change, and **run 2 confirms it by observation** (median 37.4 → 37.5 ms,
identical 37.3 ms floor), rather than leaving it as inference.

## AC-5

`.venv/bin/pytest -m "not integration"`:

```
====================== 490 passed, 5 deselected in 15.17s ======================
```

490 passed, no failures. (485 before merging `dev`; FTHR-021 added 5 unit tests
pinning the DEVNULL call shape.) The new test is `@pytest.mark.integration`, so
it is among the 5 deselected and adds nothing to the unit run.

Lint clean — `.venv/bin/ruff check tests/test_inject.py` → `All checks passed!`;
`.venv/bin/ruff format --check tests/test_inject.py` → `1 file already formatted`.

## Change summary

One file touched: `tests/test_inject.py`.

- Added `test_paste_round_trip_latency` (`@pytest.mark.integration`): 10 real
  `ClipboardManager.copy()` + `Injector.paste()` round-trips against the short
  representative delta `" streaming"`, timed with `time.monotonic()`, logged at
  INFO. Real components, not mocked — a mocked `subprocess.run` would make the
  measurement meaningless.
- Added local `_save_clipboard` / `_restore_clipboard` helpers, mirroring
  `test_clipboard.py`'s existing pair (that file's `_completed` helper is
  likewise duplicated across the two test modules, so this matches existing
  style rather than introducing shared test infrastructure). Both take a
  `primary` flag so the test restores both selections `copy()` writes.
  `_restore_clipboard` uses DEVNULL, not `capture_output` — see AC-4.
- Skip guards match the repo convention exactly: `STENOGRAPHER_INTEGRATION=1`,
  plus `wl-copy` / `wtype` on PATH and `WAYLAND_DISPLAY` set.

No source module was modified. `bench.py` was not extended — per the spec this
is deliberately one test, not a benchmarking subsystem.
