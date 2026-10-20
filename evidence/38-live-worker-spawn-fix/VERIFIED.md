# VERIFIED — 38-live-worker-spawn-fix

Verifier re-run on 2026-10-19 at commit 1cce8bd. The worktree has no `.venv`.
Tools came from `/home/penguin/source/stenographer/.venv/bin` with
`PYTHONPATH=$PWD/src`. `stenographer.__file__` resolved to this worktree's `src/`.

Red runs used a scratch worktree at the base `1723f96` with only the new tests
applied. Mutation runs then applied the task's `src` diff there and changed one
line at a time. The scratch worktree was removed afterwards.

Grouped command (all items):
`pytest -q tests/cli/live/test_handler.py tests/cli/live/test_app.py tests/lib/live/test_live_session.py tests/lib/platform/test_live_spawn_under_textual.py`

| Item | Result | Observation |
| --- | --- | --- |
| V1 Spawn under Textual stderr | pass | Red at base: the real-spawn test failed in its child process with `ValueError: bad value(s) in fds_to_keep`. Mutation (handler skips `session.start()`): the spawn test and both handler tests failed. Green: passed. The child only loads a model on a `load` request; the test never sends one and closes the child at once. |
| V2 Load before the app | pass | Red at base: handler events `['app', 'stop']` instead of `['start', 'app', 'stop']`; load-failure test returned 0; session events `['hold']` without `warmup`. Mutation (no `warmup()` in `start`): 2 session tests failed. Green: passed. |
| V3 Meter mapping and floor | pass | Red at base: `_format_meter() takes 1 positional argument but 2 were given`; `meter_floor_dbfs` absent. Expected cells re-derived by hand (floor -70, top -10, 12 dB per cell): -80→0, -70→0, -50→1, -40→2, -20→4, -10→5, -inf→0. They match the test. Mutation (old `+60 / 12` formula): mapping and Pilot tests failed. |
| V4 Meter refresh while running | pass | Red at base: status showed `m ON [····· -50 dBFS]`, expected `█····`. Green: passed. |
| V5 Failed phrase count | pass | Red at base: `failed_phrase_count` absent; status lacked `failed phrases 2`. Mutation (no increment): the count test failed. Green: passed. |
| V6 Gate | pass | `ruff check .`: `All checks passed!`. `ruff format --check .`: `589 files already formatted`. `pytest -m "not integration"`: `2547 passed, 2 skipped, 6 deselected`. `stenographer --help`: exit 0, lists `live`. |

Grouped counts: base with new tests `11 failed, 10 passed`; fixed `21 passed`.
V1.md reports `9 failed, 11 passed`; that count predates commit 8bb9097, which
added one test and changed one expected event list. The difference is
consistent with that commit.

Note on R1: the worker primes the resource tracker by spawning the real child
(`session.start()` → `warmup()`) before `App.run`, in place of
`resource_tracker.ensure_running()`. The regression test shows a second spawn
inside the app with `fileno() == -1` stderr succeeds. The evidence does not
state why `ensure_running()` was not chosen; the behaviour requirement is met.

No microphone, system audio capture, integration test, model load, or network
call ran. Real-audio acceptance belongs to the manager and the user after
landing.
