# FTHR-021 — Fix ClipboardManager.copy() hanging on captured wl-copy pipes

Evidence file. Each section records the commands run and their verbatim output,
captured at the time the criterion was satisfied.

All commands run from the worktree
`/home/penguin/source/stenographer/.fledge/burrows/FTHR-021` on branch
`feather/FTHR-021-fix-clipboard-hang`, using a **worktree-local** venv. The main
checkout's venv is an editable install pointing at the main checkout's `src/`;
using it here would silently test the wrong code. Verified before any test ran:

```
$ .venv/bin/python -c "import stenographer, os; print(os.path.realpath(stenographer.__file__))"
/home/penguin/source/stenographer/.fledge/burrows/FTHR-021/src/stenographer/__init__.py
```

## AC-1

Implementation order was fixed: tests written first, run against unchanged code,
observed failing for the expected reason, then implemented.

### Pre-fix: unit pin (`test_copy_does_not_capture_subprocess_pipes`)

```
$ .venv/bin/pytest tests/test_clipboard.py::test_copy_does_not_capture_subprocess_pipes -q
E               AssertionError: ['wl-copy'] must not capture wl-copy's pipes: the forked clipboard daemon inherits them and holds them open
E               assert True is not True
E                +  where True = <built-in method get of dict object at 0x7f5528eb0440>('capture_output')
E                +    where <built-in method get of dict object at 0x7f5528eb0440> = {'input': b'hello', 'check': True, 'timeout': 10.0, 'capture_output': True}.get
E                +      where {'input': b'hello', 'check': True, 'timeout': 10.0, 'capture_output': True} = call(['wl-copy'], input=b'hello', check=True, timeout=10.0, capture_output=True).kwargs

tests/test_clipboard.py:92: AssertionError
=========================== short test summary info ============================
FAILED tests/test_clipboard.py::test_copy_does_not_capture_subprocess_pipes
1 failed in 0.02s
```

Fails on the assertion, not on an import or a skip.

### Pre-fix: integration test (`test_clipboard_copy_real_wl_copy_round_trip`)

Run against unchanged code, with orchestrator clearance for the real clipboard.
This is the load-bearing evidence of the feather: the failure is the **real 10s
timeout**, not a skip and not an import error. The elapsed time is what proves
the test actually reached the defect.

```
$ STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest "tests/test_clipboard.py::test_clipboard_copy_real_wl_copy_round_trip" -q --durations=3
>           assert result is True, (
                f"copy() returned False after {elapsed:.2f}s -- if elapsed is near "
                "the 10.0s timeout, wl-copy's forked daemon is holding captured pipes"
            )
E           AssertionError: copy() returned False after 10.01s -- if elapsed is near the 10.0s timeout, wl-copy's forked daemon is holding captured pipes
E           assert False is True

tests/test_clipboard.py:277: AssertionError
============================= slowest 3 durations ==============================
10.04s call     tests/test_clipboard.py::test_clipboard_copy_real_wl_copy_round_trip

(2 durations < 0.005s hidden.  Use -vv to show these durations.)
=========================== short test summary info ============================
FAILED tests/test_clipboard.py::test_clipboard_copy_real_wl_copy_round_trip
1 failed in 10.06s
```

`copy()` returned `False` after **10.01s** — the full `timeout=10.0` plus
overhead. The failure is the hang itself, against the real `wl-copy`, from
Python. Every mocked unit test in the suite passed on this same code.

### Post-fix: both tests pass

```
$ STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest "tests/test_clipboard.py::test_clipboard_copy_real_wl_copy_round_trip" -q --durations=3
.                                                                        [100%]
============================= slowest 3 durations ==============================
0.07s call     tests/test_clipboard.py::test_clipboard_copy_real_wl_copy_round_trip

(2 durations < 0.005s hidden.  Use -vv to show these durations.)
1 passed in 0.08s
```

**10.04s → 0.07s.** No test was weakened, skipped, or deleted to get there; the
only assertion changed was one that asserted the defect (see AC-5).

## AC-2

`copy()` returns `True` against a real `wl-copy` and completes without hitting
its timeout — paste mode is functional on real hardware. Shown by the post-fix
run above: `1 passed`, with the test asserting both `result is True` and
`elapsed < 5.0`. Measured call duration is **0.07s** for the whole test
(two `wl-copy` invocations plus three `wl-paste` readbacks), against a pre-fix
**10.01s** for `copy()` alone.

The duration bound is the behaviour under test — "does not hang" — not a latency
budget, which is why the 5.0s bound is deliberately generous rather than tight.
The 10.0s timeout is left in place: a now-0.07s call keeping a 10s ceiling is
harmless, and retuning it is not this feather's subject.

## AC-3

Both selections are populated by a single `copy()` call. The integration test
asserts, after one `copy(token)`:

- `_read_selection(primary=False) == token` — via `wl-paste --no-newline`
- `_read_selection(primary=True) == token` — via `wl-paste --no-newline --primary`
- `mgr.read() == token` — exercising `ClipboardManager.read()` against real `wl-paste`

Passing (see the post-fix run above). **This is the first time PLM-009 FC-1/FC-2's
dual-population design has ever executed.** Pre-fix, `copy()` returned `False` on
the first `wl-copy`'s timeout, so `["wl-copy", "--primary"]` was never reached and
the primary selection was never written — which is what the pre-fix failure
captured under AC-1 demonstrates.

## AC-4

**The strict return contract is unchanged.** `copy()` still returns `True` only
if *both* the regular and `--primary` writes succeed:

- The loop shape is untouched — `for argv in (["wl-copy"], ["wl-copy", "--primary"])`
  with `return False` inside the `except` and `return True` only after the loop
  completes. The diff changes only the output redirection inside the
  `subprocess.run` call.
- `check=True` still works: the return code is still collected, since only
  stdout/stderr are redirected.
- The unmodified `test_copy_called_process_error_returns_false`,
  `test_copy_timeout_returns_false`, and `test_copy_file_not_found_returns_false`
  continue to pass, pinning `False` on each failure mode.

This contract is load-bearing: it is what makes a partial-clipboard desync
detectable to `LiveStreamer._emit()` and the reason FTHR-017's prefix invariant
holds. It was **never actually exercised before this feather** — `copy()` always
short-circuited on the first timeout. The loop now genuinely reaches the second
call for the first time.

No threads, no `Popen` plumbing, no clipboard daemon. `--foreground` was not
used: it keeps the process in the foreground precisely so it can serve the
selection, which is the opposite of what is wanted, and it was measured still
timing out.

## AC-5

`test_copy_does_not_capture_subprocess_pipes` is the unit-level pin. It asserts
both `wl-copy` calls pass neither `capture_output=True` nor anything but
`subprocess.DEVNULL` for stdout/stderr.

**Stated plainly: this pins the **call shape**, not the behaviour.** It cannot
prove the behaviour, because it patches `subprocess.run` — the very fork that is
the defect is what the mock replaces. A mocked test can never observe this bug.
Its narrow job is to stop a future refactor from "tidying" the call back to
`capture_output=True` and silently restoring a 10s hang.
`test_clipboard_copy_real_wl_copy_round_trip` is the test that proves the
behaviour; this one guards it.

**One existing assertion was changed, with orchestrator clearance, and it
matters.** `test_copy_success_returns_true_and_pipes_input` contained:

```python
assert call.kwargs["capture_output"] is True
```

That line asserted the defect was the contract. It could not survive the fix —
it is the exact inverse of the new pin. Per the spec's instruction not to edit
existing tests unilaterally, this was escalated rather than decided; the
orchestrator cleared changing that single line to assert the new call shape,
leaving `input`, `check`, and `timeout` untouched.

Deliberately **not** changed: `test_read_success_strips_trailing_newline` still
asserts `capture_output is True` — on **`wl-paste`**, where it is correct and
required. `wl-paste` does not fork a daemon, and `read()` needs its stdout.
`ClipboardManager.read()` is unchanged.

## AC-6

**Finding: `Injector.paste()` is NOT affected. Documented as unaffected, not
fixed.** Determined from documented behaviour, without executing `wtype` (the
brooder is barred from invoking it).

The root cause is specific to `wl-copy`'s fork, confirmed independently from its
own man page rather than assumed from the spec:

```
$ man wl-copy
     -f, --foreground (for wl-copy)
            By default, wl-copy forks and serves data requests in the back-
            ground; this option overrides that behavior, causing wl-copy to run
            in the foreground.
```

"forks and serves data requests in the background" is the defect verbatim: the
forked child inherits the stdout/stderr pipes `capture_output=True` creates, and
`subprocess.run` waits for EOF on pipes that child holds open for as long as the
selection is offered.

`wtype` has no such child. Per `man wtype`:

```
     Beware that the modifiers get released automatically once the program
     terminates.
```

`wtype` terminates when it is done typing — that is the documented basis of its
modifier semantics. It offers no selection, serves no data requests, and forks
no background process, so nothing survives to hold an inherited pipe open.
`subprocess.run` sees EOF at process exit and returns normally. `capture_output=True`
in `Injector.paste()` and `Injector.type_text()` is therefore harmless.

Further, it is not merely harmless but **load-bearing**: both methods read
`exc.stderr` in their `CalledProcessError` handlers to log wtype's diagnostics
(`inject.py` lines 61-65 and 101-105). Switching them to `DEVNULL` would
silently blank that error logging. Changing `inject.py` here would be a
regression, not a fix.

Note this was genuinely unproven rather than known-good before this check:
FTHR-018's human-attended run died at `copy()` and never reached `paste()`.

## AC-7

`live.py`, `session.py`, and `formatter.py` are untouched, along with
`inject.py` (see AC-6). Verified rather than asserted:

```
$ git diff --stat
 src/stenographer/output/clipboard.py |  10 ++-
 tests/test_clipboard.py              | 119 ++++++++++++++++++++++++++++-------
 2 files changed, 106 insertions(+), 23 deletions(-)

$ git diff --name-only -- src/stenographer/live.py src/stenographer/session.py src/stenographer/output/formatter.py src/stenographer/output/inject.py
(no output)
```

Exactly two files changed. FTHR-017's `_delivery_failed` latch and FTHR-020's
clipboard-fallback behaviour are unchanged, and their tests pass unmodified:

```
$ .venv/bin/pytest tests/test_live.py tests/test_inject.py -q -m "not integration"
52 passed, 1 deselected in 0.17s
```

The latch is correct and needed no change: once `copy()` works, it simply stops
firing.

## AC-8

```
$ .venv/bin/pytest -m "not integration" -q
490 passed, 4 deselected in 15.40s
```

No regressions. (489 pre-existing tests, plus the new unit pin; the superseded
`test_real_wl_copy_round_trip` was integration-marked and so was never in this
count.)

Lint and format clean:

```
$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/ruff format --check .
55 files already formatted
```

### Note: the superseded integration test — a second finding

`test_real_wl_copy_round_trip` was replaced by
`test_clipboard_copy_real_wl_copy_round_trip` with orchestrator clearance. The
replacement is strictly stronger on every axis the old one covered: it keeps the
`copy() is True` assertion and the real-`wl-paste` `mgr.read()` round-trip
(tightened from `sentinel in result` to `== token`), and adds the duration bound,
the `--primary` readback, and save/restore of *both* selections.

**Worth recording prominently: that test already existed, and was already red on
`dev`.** It asserted `copy() is True` against a real `wl-copy` — it would have
caught this defect at any point since it was written. It never did, because
nothing runs the integration suite: it is gated behind `STENOGRAPHER_INTEGRATION`
and no automation sets it. So `STENOGRAPHER_INTEGRATION=1 pytest` has been red on
`dev` with nobody watching.

The implication is sharper than "we lacked a test." The blind spot was known well
enough to write a test for, and the test still didn't close it. The gap was never
authorship — it was that nothing executed it. (The automation gap itself is out of
this feather's scope; the orchestrator is raising it separately.)

Its old `_restore_clipboard` helper also used `capture_output=True` on `wl-copy`,
so it silently ate a 10s timeout on every teardown — the same defect, in the test
infrastructure meant to catch it. The new `_restore_selection` uses `DEVNULL`.

## AC-9

**This is a v1-era latent defect, not a PLM-009/PLM-010 regression.** Verified
against history rather than taken from the spec:

```
$ git log --oneline -S 'capture_output' -- src/stenographer/output/clipboard.py | tail -3
f20ee52 v1
```

`capture_output=True` in `copy()` has been present since `f20ee52` ("v1"). The
only later commit to touch the file is `1465de7` ("feat: fire Shift+Insert and
populate the primary selection", FTHR-016), which added the `--primary` call but
did **not** introduce the capture. PLM-009/PLM-010 inherited the defect; they did
not cause it.

What those feathers did was make it *visible*. FTHR-017 began consuming
`copy()`'s return value, so a `False` that had always been discarded started
latching `_delivery_failed`. FTHR-017 and FTHR-020 are behaving correctly — they
are faithfully handling a failure that should never have been occurring.

**PLM-009's FC-1/FC-2 were satisfied in code but never executed.** The
dual-population design was real and correct in source, yet `copy()` returned
`False` on the first `wl-copy`'s timeout every time, so the loop never reached
`["wl-copy", "--primary"]`. The primary selection has never once been populated
in production. FC-1/FC-2 passed review on code that had never run.

**Why 489 tests missed it — and worse.** Every clipboard unit test mocks
`subprocess.run`, replacing the very fork that is the defect, so they can only
ever pin the code's intent. FTHR-015's manual probe passed because a shell
`printf 'x' | wl-copy` does not capture pipes. The defect lives exactly in the
gap: reachable only by invoking the real binary from Python.

**The headline finding — the suite did not merely fail to catch this bug. It
asserted the bug was correct.** `test_copy_success_returns_true_and_pipes_input`
contained:

```python
assert call.kwargs["capture_output"] is True
```

That is a test pinning a 10-second hang in place and calling it the contract. It
was green on every run. Any attempt to fix the defect would have "broken the
tests" — the suite was actively defending the bug.

This is why 489 tests, three merged feathers, and adversarial review all sailed
past a feature that did not work. **The blind spot was not an absence of
coverage. It was coverage pointed at the wrong thing.** The clipboard code was
thoroughly tested; every one of those tests mocked away the only component whose
real behaviour mattered — `wl-copy`'s fork — and then pinned the mock's shape as
the specification. A test that asserts the arguments to a mocked subprocess can
only ever confirm that the code does what it does. It says nothing about whether
that works.

Two independent signals were both misread as green:

1. The unit suite passed because it mocked the defect away.
2. FTHR-015's manual probe passed because a shell `printf 'x' | wl-copy` does not
   capture pipes — a different execution shape from the one that ships.

The defect lived exactly in the gap between them: reachable only by invoking the
real binary from Python, which nothing did until FTHR-018's human-attended run.

The transferable lesson: when a test mocks the process boundary that a defect
lives on, passing tells you nothing about the boundary — and if that test also
asserts the mock's call shape, it converts the unknown into a false guarantee and
then defends it against repair. The integration test in this feather is the
deliverable that closes that gap; the unit pin (AC-5) only guards the fix's shape
and is explicitly not evidence of behaviour.
</content>
