# VERIFIED — 61-hub-live

Verifier run on 2026-10-20 at `99cc2ea` (base `ac454bc`, `origin/dev`). The
worktree has no `.venv`, so the verifier used
`/home/penguin/source/stenographer/.venv/bin` (Python 3.14.8) with
`PYTHONPATH="$PWD/src"`; the import resolved to this worktree's
`src/stenographer`. Each item was re-run with the commands in `V<n>.md`. Red
runs used a temporary worktree at the base with the new test file copied in.

| Item | Result | Observation |
| --- | --- | --- |
| V1 red: `pytest -q tests/cli/hub/test_live_view.py` at base `ac454bc` | pass | `3 failed`: hub shows the "Recording is active" placeholder, no `#speaker-select` rename dialog, and keys make no session calls. V1.md says `2 failed`; the file now also holds the rename test |
| V1 green: `pytest -q tests/cli/hub/test_live_view.py tests/cli/live/test_app.py` | pass | `10 passed` |
| V2: `pytest -q tests/cli/hub/test_app.py tests/cli/live/test_app.py` | pass (flaky test noted) | First run `1 failed, 14 passed`; then `15 passed` in 43 of 45 repeats. See the flake note below |
| V2: `tests/cli/live/test_app.py` unchanged from base (nonblocking stop regression kept) | pass | `git diff ac454bc HEAD -- tests/cli/live/` is empty |
| V3 `ruff check .` | pass | `All checks passed!` |
| V3 `ruff format --check .` | pass | `619 files already formatted` |
| V3 `pytest -m "not integration"` | pass | `2610 passed, 2 skipped, 6 deselected`; skips need absent public audio samples |
| V3 `stenographer --help` | pass | exit 0, usage printed |
| Docs say which `stenographer live` mode was kept | pass | README.md and docs/live.md: standalone app, existing flags kept, does not open the hub |
| No mic, recording, `live`/`run`, model download, integration tests, push of dev/main, PR, or workflow | pass | None run by the verifier |

## Flake note

`tests/cli/hub/test_app.py::test_pilot_slow_recording_start_keeps_hub_responsive`
fails sometimes with `WorkerFailed: NoMatches("No nodes match '#sidebar'")`.
The `start-recording` worker calls `_refresh_view()` after the test app has
torn down. The test and `_start_recording` both exist unchanged at base.

| Run | Base `ac454bc` | Task `99cc2ea` |
| --- | --- | --- |
| V2 command, serial | 0 / 30 failed | 2 / 45 failed |
| That test alone, 4-way parallel load | 1 / 100 failed | 4 / 100 failed |

The race exists at base. The task's 0.1 s Live refresh interval may raise
the rate, but these counts do not prove it. A fix (for example, guard
`_refresh_view` after unmount) is outside this task's scope and is left to
the manager.

Pilot tests use fake services and a fake session. Real recording, levels,
source toggles, and stop-and-save on a live session are left to real-machine
acceptance.

## Verdict

Pass. Each item passes. One test that existed before this task fails now and
then (see the flake note).
