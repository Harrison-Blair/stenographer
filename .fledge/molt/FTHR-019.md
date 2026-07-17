# FTHR-019 evidence

Add `trigger_mode = "ptt"` as a third `HotkeyStateMachine` mode and make it
`Config.defaults()`'s default.

Environment: worktree `.fledge/burrows/FTHR-019`, branch
`feather/FTHR-019-ptt-trigger-mode` (from `dev`). All tooling via a
**worktree-local** venv, built fresh because the main checkout's venv is an
editable install pointing at the MAIN checkout's `src/` and would silently test
the wrong tree:

```
python3 -m venv .venv && .venv/bin/pip install -e ".[dev,build]"
.venv/bin/python -c "import stenographer; print(stenographer.__file__)"
/home/penguin/source/stenographer/.fledge/burrows/FTHR-019/src/stenographer/__init__.py
```

Resolves inside the worktree — results below are about this branch's code.

## AC-1

The tests were observed FAILING before implementation and passing after.

### Pre-implementation run (captured against unchanged `src/`)

`src/` was confirmed untouched at capture time — only the test files were
written:

```
$ git status --porcelain src/
(no output — src/ untouched)
$ git diff --stat
 tests/test_config.py | 21 +++++++++++++++---
 tests/test_hotkey.py | 63 +++++++++++++++++++++++++++++++++++++++++++++++++++-
 2 files changed, 80 insertions(+), 4 deletions(-)
```

```
$ .venv/bin/pytest -m "not integration" \
    tests/test_hotkey.py::test_ptt_mode_keydown_always_starts_recording \
    tests/test_hotkey.py::test_ptt_mode_keyup_always_stops_unconditionally \
    tests/test_hotkey.py::test_ptt_mode_short_tap_does_not_enter_pending_tap \
    tests/test_hotkey.py::test_ptt_mode_cancel_aborts_recording \
    tests/test_config.py::test_trigger_mode_accepts_ptt \
    tests/test_config.py::test_defaults_trigger_mode_is_ptt --tb=line

============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/penguin/source/stenographer/.fledge/burrows/FTHR-019
configfile: pyproject.toml
plugins: anyio-4.14.2, asyncio-1.4.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 6 items

tests/test_hotkey.py FFFF                                                [ 66%]
tests/test_config.py FF                                                  [100%]

=================================== FAILURES ===================================
E   ValueError: mode must be 'hybrid' or 'toggle', got 'ptt'
/home/penguin/source/stenographer/.fledge/burrows/FTHR-019/src/stenographer/hotkey/state_machine.py:62: ValueError: mode must be 'hybrid' or 'toggle', got 'ptt'
E   ValueError: mode must be 'hybrid' or 'toggle', got 'ptt'
/home/penguin/source/stenographer/.fledge/burrows/FTHR-019/src/stenographer/hotkey/state_machine.py:62: ValueError: mode must be 'hybrid' or 'toggle', got 'ptt'
E   ValueError: mode must be 'hybrid' or 'toggle', got 'ptt'
/home/penguin/source/stenographer/.fledge/burrows/FTHR-019/src/stenographer/hotkey/state_machine.py:62: ValueError: mode must be 'hybrid' or 'toggle', got 'ptt'
E   ValueError: mode must be 'hybrid' or 'toggle', got 'ptt'
/home/penguin/source/stenographer/.fledge/burrows/FTHR-019/src/stenographer/hotkey/state_machine.py:62: ValueError: mode must be 'hybrid' or 'toggle', got 'ptt'
E   stenographer.config.ConfigError: /tmp/pytest-of-penguin/pytest-2/test_trigger_mode_accepts_ptt0/config.toml: hotkey.trigger_mode: must be one of ['hybrid', 'toggle']
/home/penguin/source/stenographer/.fledge/burrows/FTHR-019/src/stenographer/config.py:309: stenographer.config.ConfigError: /tmp/pytest-of-penguin/pytest-2/test_trigger_mode_accepts_ptt0/config.toml: hotkey.trigger_mode: must be one of ['hybrid', 'toggle']
E   AssertionError: assert 'hybrid' == 'ptt'

      - ptt
      + hybrid
/home/penguin/source/stenographer/.fledge/burrows/FTHR-019/tests/test_config.py:276: AssertionError: assert 'hybrid' == 'ptt'
=========================== short test summary info ============================
FAILED tests/test_hotkey.py::test_ptt_mode_keydown_always_starts_recording - ...
FAILED tests/test_hotkey.py::test_ptt_mode_keyup_always_stops_unconditionally
```

All six fail for the expected reason: `"ptt"` is not yet a valid mode
(`ValueError` from the state machine, `ConfigError` from config), and
`defaults()` still returns `'hybrid'`. The two default-asserting tests updated
per AC-5 also failed here, confirming they bind to the new behavior:

```
FAILED tests/test_config.py::test_defaults_hotkey - AssertionError: assert Ho...
FAILED tests/test_config.py::test_format_default_toml_has_trigger_mode - asse...

E       AssertionError: assert HotkeyConfig(...mode='hybrid') == HotkeyConfig(...er_mode='ptt')
E         Differing attributes:
E         ['trigger_mode']
E           trigger_mode: 'hybrid' != 'ptt'
```

### Post-implementation run

Same 8 node IDs, after implementing `state_machine.py` + `config.py`:

```
$ .venv/bin/pytest -m "not integration" <same 8 node ids>
tests/test_hotkey.py ....                                                [ 50%]
tests/test_config.py ....                                                [100%]

============================== 8 passed in 0.03s ===============================
```

### Test sensitivity (mutation checks)

A test that has only been seen passing does not count. The pre-implementation
failures above were all "mode invalid" errors, which prove the tests bind to
`ptt` existing but NOT that they bind to its *behavior*. So each branch was
mutated on the finished code and the tests re-run:

**Mutation 1 — delete the `ptt` early-return in `on_keyup`** (fall through to
hybrid's duration logic):

```
FFF.                                                                     [100%]
FAILED tests/test_hotkey.py::test_ptt_mode_keydown_always_starts_recording
FAILED tests/test_hotkey.py::test_ptt_mode_keyup_always_stops_unconditionally
FAILED tests/test_hotkey.py::test_ptt_mode_short_tap_does_not_enter_pending_tap
3 failed, 1 passed, 38 deselected in 0.03s
```

Load-bearing and genuinely covered — this is the branch that does the work.

**Mutation 2 — delete the `ptt` branch in `on_keydown`: 4 passed (NO failure).**
This surfaced real redundancy rather than a test gap: hybrid's `IDLE` branch
already returns an identical `Transition("start_recording", "ptt_on")` and sets
`RECORDING_PTT`. The only true delta for `ptt` is that it must not record
`_press_start`. The duplicated branch was therefore simplified to express only
that delta (`if self._mode != "ptt": self._press_start = timestamp`), which is
also exactly what the feather's Approach describes ("behave like today's IDLE →
hybrid's RECORDING_PTT transition but unconditionally"). Mutation 1 was re-run
against the simplified code and still fails 3 tests (output identical to above).

**Mutation 3 — force `ptt` to record `_press_start` anyway: 4 passed (NO
failure).** Reported openly rather than papered over: `_press_start` is private
and never read on the `ptt` path, so the mutation is unobservable through the
public API. Closing this would mean asserting on private state, which no
existing test in this file does. The guard is retained as a structural
invariant ("ptt never consults duration"), not because a test forces it.

## AC-2

`HotkeyStateMachine(mode="ptt")` always starts on keydown and always stops on
keyup, for very short and long presses. Covered by
`test_ptt_mode_keydown_always_starts_recording` and
`test_ptt_mode_keyup_always_stops_unconditionally`, each looping over BOTH a
10ms tap and a 5s hold (`for keyup_at in (0.01, 5.0)`) against
`threshold_seconds=0.5` — i.e. one release far below the threshold and one far
above, both yielding `stop_recording_ptt` / `ptt_off` / `IDLE`. See the
Mutation 1 result above for proof these assertions are load-bearing.

## AC-3

`PENDING_TAP` / `TOGGLE_LATCHED` are unreachable in `ptt` mode.

Test: `test_ptt_mode_short_tap_does_not_enter_pending_tap` — a 50ms tap
(well under the 0.5s threshold) returns `stop_recording_ptt` and lands in
`IDLE`, never `PENDING_TAP`; a second tap 50ms later (inside what would be the
0.35s double-tap window) returns `start_recording` and `RECORDING_PTT`, NOT
`latch_toggle` / `TOGGLE_LATCHED`.

Structural argument (why unreachable, not merely untested): in `on_keydown`,
`TOGGLE_LATCHED` is entered only from the `mode == "toggle"` branch or from
`_state == "PENDING_TAP"`. In `on_keyup`, `PENDING_TAP` is entered only on the
hybrid duration path, which `ptt` now returns before reaching.
`TOGGLE_STOPPING` is entered only from `TOGGLE_LATCHED`. So with no route into
`PENDING_TAP` or `TOGGLE_LATCHED`, all three states are unreachable when
`mode == "ptt"`.

## AC-4

`config.py` accepts `hotkey.trigger_mode = "ptt"` and still rejects unknown
values with the existing `ConfigError` shape. `ALLOWED_TRIGGER_MODES` gained
`"ptt"`; no other config logic changed.

Test `test_trigger_mode_accepts_ptt` asserts both halves: `"ptt"` loads, and
`"nonsense"` raises `ConfigError` matching `hotkey.trigger_mode`. Pre-impl it
failed with the unchanged error shape, which is also the shape still asserted:

```
E   stenographer.config.ConfigError: .../config.toml: hotkey.trigger_mode: must be one of ['hybrid', 'toggle']
```

## AC-5

`Config.defaults().hotkey.trigger_mode == "ptt"` — a deliberate user-facing
default change (`hybrid` → `ptt`), asserted by `test_defaults_trigger_mode_is_ptt`.

## AC-6

The cancel binding still aborts an active `ptt` recording with no output side
effect. Test: `test_ptt_mode_cancel_aborts_recording` — `on_cancel()` during
`RECORDING_PTT` returns `cancel`/`cue="cancel"` and lands in `IDLE`; the
cancelled press's keyup then returns `noop` (consumed), so no
`stop_recording_ptt` fires and nothing is transcribed or typed; the next press
starts fresh.

Confirmed (not assumed) that `on_cancel()` needs no `ptt`-specific change: it
reads `_chord_active` and writes `_pending_generation`/`_press_start`/`_state`/
`_consumed` only — it never branches on `_mode`. It is unchanged in this diff.

## AC-7

Existing `hybrid` and `toggle` **behavior** tests pass **unmodified**. Not one
was edited: `test_ptt_path_keydown_then_long_keyup`,
`test_double_tap_toggle_full_cycle`, `test_short_tap_enters_pending_then_timeout_discards`,
`test_toggle_mode_single_press_latches`, `test_toggle_mode_long_hold_is_not_ptt`,
`test_exactly_threshold_is_ptt`, the cancel tests, and the listener tests are
all byte-for-byte unchanged (`git diff` touches no line inside them).

```
$ .venv/bin/pytest -m "not integration" tests/test_hotkey.py \
    -k "ptt_path or double_tap or toggle_mode or pending or threshold or cancel or listener"
tests/test_hotkey.py .......................                             [100%]
====================== 23 passed, 19 deselected in 0.51s =======================
```

### Existing tests that WERE changed, and why (full disclosure)

Four existing tests were changed. None is a `hybrid`/`toggle` behavior test;
all four asserted the exact facts this feather is chartered to change. Escalated
to `team-lead` before implementing.

1. `test_hotkey.py::test_state_machine_rejects_unknown_mode` — used `"ptt"` as
   its example of an INVALID mode. Irreconcilable with AC-2. Sentinel repointed
   `"ptt"` → `"bogus"`; the assertion (unknown modes raise `ValueError`) is
   preserved, not weakened.
2. `test_config.py::test_hotkey_trigger_mode_invalid_rejected` — same problem;
   sentinel repointed `"ptt"` → `"bogus"`, still asserts `ConfigError`.
3. `test_config.py::test_defaults_hotkey` — full `HotkeyConfig` equality;
   `trigger_mode="hybrid"` → `"ptt"` per AC-5.
4. `test_config.py::test_format_default_toml_has_trigger_mode` — asserts the
   generated default TOML; `"hybrid"` → `"ptt"` per AC-5. (`_format_default_toml`
   emits from `defaults()`, so this tracks AC-5 automatically.)

Items 3 and 4 were observed FAILING pre-implementation (see AC-1), so they bind
to the new intended default rather than having been edited to fit.

## AC-8

Full unit suite passes, no regressions:

```
$ .venv/bin/pytest -m "not integration"
====================== 476 passed, 4 deselected in 15.55s ======================

$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/ruff format --check .
55 files already formatted
```

## Scope

Two source files changed, exactly those the feather names:

```
$ git status --porcelain src/
 M src/stenographer/config.py
 M src/stenographer/hotkey/state_machine.py
```

`session.py`, `output/`, and `live.py` are untouched — this feather stays
disjoint from FTHR-016. Confirmed by grep that `trigger_mode` appears only in
`config.py` and at `cli.py:222`, never in `session.py`.

**`cli.py:222` needed no change, confirmed empirically** rather than assumed —
it is a generic pass-through, so the new default flows end-to-end with zero cli
edits:

```
$ .venv/bin/python -c "<construct HotkeyStateMachine from Config.defaults() exactly as cli.py:219-223 does>"
cfg default trigger_mode : ptt
keydown                  : Transition(action='start_recording', cue='ptt_on')
keyup after 10ms         : Transition(action='stop_recording_ptt', cue='ptt_off')
final state              : IDLE
```

A 10ms tap through the real default config path starts and stops recording —
the AC-2/AC-5 behavior wired together as the daemon would.

