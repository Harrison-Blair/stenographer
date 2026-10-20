# Task: hub-refresh-race — stop hub workers touching an unmounted app

| Item | Value |
| --- | --- |
| Tier | small |
| Depends on | 61 (hub-live), 72 (tui-input-first), both landed |

## Overview

`tests/cli/hub/test_app.py::test_pilot_slow_recording_start_keeps_hub_responsive`
fails intermittently with `WorkerFailed: NoMatches("No nodes match '#sidebar'")`.
The `start-recording` worker (`cli/hub/app.py`, `_start_recording`) calls
`_refresh_view()` after the app has been torn down. Measured by the task 61
verifier: 1/100 failures at `ac454bc` under 4-way parallel load, 4/100 at the
task 61 head, 2/45 serially. A real user can hit the same race by quitting
while a start, stop, save or cancel worker is still finishing.

## Requirements

1. Hub lifecycle workers (start, stop, save, Files cancel, and any other
   Textual worker in `cli/hub/` that refreshes the view when done) must not
   touch widgets after the app or screen has unmounted. Guard the refresh
   (for example, check `is_mounted` or catch `NoMatches` only at that one
   point) or cancel the workers on unmount. Pick the smallest fix that
   covers every such worker. Do not hide other errors.
2. Regression test: a pilot test that deterministically ends the app while
   a lifecycle worker is still running (control the worker with an event,
   not a sleep), and asserts no worker failure. It fails at base, then
   passes.
3. Stability evidence: run `test_pilot_slow_recording_start_keeps_hub_responsive`
   100 times under 4-way parallel load at the fix head: 0 failures. Record
   the counts.

## Common rules

- Goal: `.hive/tmp/coordinator/goal-stenographer-hub.md` in the hive home
  (decisions 1 to 15). Design boards: `.hive/tmp/coordinator/designs/stenographer/`.
  Plan review: `.hive/tmp/reports/plan-review-stenographer.md`. Read the parts
  that apply. The boards set layout and content, not exact colours or sizes.
  The board `Config.dc.html` shows two profile columns. That is out of date
  (decision 15): one column of ASR settings.
- Grant: `grants.md 2026-10-19 stenographer hub tasks` (merge to `dev` only).
- Follow the repository `AGENTS.md`. Linux only. Keep the headless core: the
  daemon and every existing subcommand keep their behaviour (decision 2).
- Evidence in `evidence/<task-id>/`, committed with `git add -f`. Never add
  evidence paths to `.gitignore` or `pyproject.toml`. Never put transcript
  text or audio in evidence, logs or history. Counts and timings are fine.
- No tautological tests. Mock only external dependencies. Each new
  regression test fails at base (show it), then passes.
- Do not open the microphone, capture audio, run `live` or `run`, download a
  model, or run integration tests. The user does those on the real machine.
- Never signal a process or close a tab, pane or workspace that you did not start; compare with the pid and pane ID recorded at start. Never work in workspace wBC (the hive session).
- Do not push `dev` or `main`, open a pull request, or run a workflow.
- Gate before `hive task complete`, with zero failures:

  ```sh
  .venv/bin/ruff check .
  .venv/bin/ruff format --check .
  .venv/bin/pytest -m "not integration"
  .venv/bin/stenographer --help
  ```
