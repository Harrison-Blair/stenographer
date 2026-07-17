# FTHR-018: Measure per-delta paste round-trip latency

Worktree: `.fledge/burrows/FTHR-018` on `feather/FTHR-018-measure-paste-latency` (cut from `dev`).
All commands run with the worktree-local venv (`.venv/bin/...`), which resolves
`stenographer` to this worktree's `src/` (verified: `pkg:
/home/penguin/source/stenographer/.fledge/burrows/FTHR-018/src/stenographer/__init__.py`).

**Oversight note (`oversight: during`).** This feather's test fires real
Shift+Insert keystrokes via `wtype` into whatever window has focus on the
user's live desktop, and mutates the real clipboard. A git worktree does not
isolate that — `wtype` talks to the real compositor. The brooder therefore did
**not** run the measurement. Every run recorded below is a *skipped-without-env-var*
run. AC-2 and AC-4 depend on a human-attended run and are recorded as pending
below; no numbers are simulated, mocked, or estimated.

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

**Honesty boundary:** the "after" state observed here is *collected and skipped*,
not *passed*. The test now exists and its node ID resolves (which is what the
pre-run failed on), and it correctly declines to run unattended. Its passing run
is the human-attended run pending under AC-2 — the brooder has not observed this
test pass.

## AC-2

**PENDING — requires a human-attended run.** Not satisfiable by the brooder; see
the oversight note above.

Command handed to the orchestrator for the user to run at a moment of their
choosing, from the worktree root:

```sh
cd /home/penguin/source/stenographer/.fledge/burrows/FTHR-018
STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest tests/test_inject.py::test_paste_round_trip_latency -s --log-cli-level=INFO
```

Before running: focus a scratch window that is safe to receive ten pasted
copies of the string `" streaming"` (a blank editor buffer or throwaway
terminal). The test saves and restores the clipboard around itself, but it
cannot undo text pasted into the focused window.

Expected log output: ten per-iteration lines plus a `min=/median=/max=` summary
line and a raw-durations list.

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

**PENDING — depends on AC-2.** The measured numbers will be written into this
section verbatim once the orchestrator returns them from the user's attended
run. Deliberately left empty rather than filled with a mocked or estimated
figure: the point of this feather is an honest real-hardware number, and a
fabricated one would be worse than none.

## AC-5

`.venv/bin/pytest -m "not integration"`:

```
tests/test_transcription.py ....                                         [ 91%]
tests/test_update.py ...................................                 [ 98%]
tests/test_worker_cancel.py .....                                        [100%]

====================== 485 passed, 5 deselected in 16.48s ======================
```

485 passed, no failures. The new test is `@pytest.mark.integration`, so it is
among the 5 deselected and adds nothing to the unit run.

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
  style rather than introducing shared test infrastructure).
- Skip guards match the repo convention exactly: `STENOGRAPHER_INTEGRATION=1`,
  plus `wl-copy` / `wtype` on PATH and `WAYLAND_DISPLAY` set.

No source module was modified. `bench.py` was not extended — per the spec this
is deliberately one test, not a benchmarking subsystem.
