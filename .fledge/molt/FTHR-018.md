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
execution (AC-2, run 0) failed against `copy()` returning `False` after a 10s
hang — the FTHR-021 P0. So this test has been observed failing twice, for two
distinct and legitimate reasons: first because it did not exist, then because
the code under it was genuinely broken.

**Passing run** — the user's attended run at commit 049888a (AC-2, run 1):

```
tests/test_inject.py::test_paste_round_trip_latency  streaming
...
PASSED

================================= 1 passed in 10.40s ==================================
```

### Status: AC-1 is not yet satisfied

Stated plainly, because an earlier revision of this document overclaimed it:

- The failing runs (collection failure, and run 0's real failure) are observed
  and real.
- The passing run above is observed and real — but it is a pass of commit
  **049888a**, and `tests/test_inject.py` changed at **89b9faf** (teardown
  helpers and their call sites). **No passing run exists for current HEAD.**
- The unit suite does not close that gap: this test is `integration`-marked, so
  it skips there. A mistake in the teardown edit would not be caught by
  `490 passed`.

AC-1 asks for a pass *after* implementation, and the implementation moved after
the last observed pass. It is claimed once run 2 lands. See AC-2, run 2.

**Provenance.** The brooder executed the pre-implementation failing run and the
collected/skipped runs. The brooder executed **none** of the real-hardware runs
— runs 0, 1, and 2 are the user's, on their hardware, relayed by the
orchestrator, because `oversight: during` forbids the brooder from firing
`wtype` at the user's live desktop.

## AC-2

**Not yet claimed — pending run 2** (see the status note under run 2 below).
A real measurement has been produced (run 1), but not against current HEAD.

Every real-hardware run was executed by the user, on their hardware, and
relayed by the orchestrator. Command (identical for all):

```sh
cd /home/penguin/source/stenographer/.fledge/burrows/FTHR-018
STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest tests/test_inject.py::test_paste_round_trip_latency -s --log-cli-level=INFO
```

Three runs are recorded below, in order. The narrative deliberately starts at
the **failing** run, not at the first passing one: this test's first real
execution found a P0, and that is the most useful thing this feather did.

- **Run 0** — first real-hardware attempt, **pre-FTHR-021**. Failed. Exposed the
  clipboard-hang P0.
- **Run 1** — post-FTHR-021 merge, pre-*this test's own* teardown fix. Passed
  with real numbers, slowly (the teardown defect under AC-4).
- **Run 2** — post-teardown-fix, at current HEAD. The confirming run.

### Run 0 — first real-hardware attempt, pre-FTHR-021 (FAILED)

This run predates the FTHR-021 merge (8d6d5df) and therefore ran against the
old `clipboard.py`, where `copy()` captured `wl-copy`'s pipes.

Observed result, **as relayed to the brooder secondhand — the brooder does not
hold this run's verbatim log**:

- `ClipboardManager.copy()` returned `False` after a ~10.01s hang (the
  `wl-copy` pipe-capture timeout).
- Total run time ~20.05s.
- The test failed at its first `assert clip.copy(...) is True`.

This is recorded at lower fidelity than runs 1 and 2 because a verbatim log was
never relayed to the brooder; the figures above are as reported by the
orchestrator, and are marked as such rather than reconstructed into a log-shaped
block that would imply a precision this record does not have.

**Why this run matters more than its numbers.** It is the run that exposed
FTHR-021 — a v1-era latent P0 in which `copy()` always returned `False` after
hanging 10s, meaning live streaming delivered nothing and every dictation
stalled. 490 mocked unit tests were green throughout, because they mocked
`subprocess.run` and so mocked away the very fork behaviour that broke. This
feather's failure, not its measurement, is what caught that.

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

### Run 2 — post-teardown-fix (commit 89b9faf) — PENDING

_Awaiting the user's confirming run. The log will be recorded here in full,
verbatim, on the same terms as run 1._

**AC-1 and AC-2 are therefore NOT yet claimed.** The reason is narrower than
"a re-run is outstanding", and worth stating precisely: run 1 passed against
the test as it stood at 049888a, but `tests/test_inject.py` has been modified
since (89b9faf changed the teardown helpers and their call sites). No passing
run exists for the code at current HEAD. The unit suite cannot cover that gap —
this test is `integration`-marked and skips there, so a helper-level mistake in
the teardown edit would not surface. The measured path (`copy()` / `paste()`)
was not touched, so the ~37 ms figures are expected to hold; but "expected to
hold" is a prediction, and AC-1's "passes after" asks for an observation. It
will be claimed when run 2 lands, and not before.

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
`Injector.paste()` (1× `wtype` Shift+Insert):

| | ms |
|---|---|
| min | **37.3** |
| median | **37.4** |
| max | **38.4** |

Raw per-iteration durations (ms): `[38.4, 37.9, 37.9, 37.5, 37.3, 37.5, 37.3,
37.3, 37.3, 37.4]`

**Conditions.** User's hardware, Hyprland/Wayland, Python 3.14.6, run from the
FTHR-018 burrow with its worktree-local venv, `delta=' streaming'`, 10
iterations, post-FTHR-021. Measured with `time.monotonic()` around `copy()` +
`paste()` only.

**Scope of the claim.** This is ~37 ms of *cost to deliver one delta*, measured
per committed word. It is not end-to-end dictation latency: ASR decode time is
excluded entirely. Whether ~37 ms/word is acceptable is deliberately not
assessed here — the user declined a latency budget (PLM-010 FC-7/AC-7), so this
section records what the cost is and leaves the judgement to the reader.

**One observation about the distribution**, offered as fact rather than verdict:
the spread is ~1.1 ms across 10 runs (37.3–38.4), and 8 of 10 iterations fall
within 0.6 ms of each other. A cost that tight is characteristic of fixed
process-spawn overhead (three `subprocess.run` calls) rather than of anything
that varies with content or system load. The practical consequence for a future
reader: this number is unlikely to improve by tuning, and would move mainly by
spawning fewer processes per delta.

### Finding: the same clipboard-restore bug existed in three copies

The user's run took **10.40s** wall-clock while the ten measured iterations sum
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

Fixed in this branch to match `clipboard.py`'s shipped form
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

Neither fix touches the measured code path (`copy()` / `paste()`), so the
numbers above stand as recorded. Both affect only teardown.

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
