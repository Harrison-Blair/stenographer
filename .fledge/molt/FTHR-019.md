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

(recorded below after implementation)
