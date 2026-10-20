# Task: tui-input-first — make the hub and `live` follow the input-first rule

| Item | Value |
| --- | --- |
| Tier | decent |
| Feature | `stenographer-hub` |
| Depends on | 60 (hub-shell, landed), 68 (hub-spec, landed) |

## Overview

The user narrowed this task on 2026-10-20. The general input-first rule
(home `overrides/tui-input-first-class.md`) is for qmeter only and does NOT
apply to stenographer. This task fixes three things only.

## Changes

- 2026-10-20: scope narrowed by the user. The Files-job quit prompt stays.
  No `ctrl+c` audit of text inputs.

## Requirements

1. Slow start and stop off the input loop. `cli/hub/app.py`
   `action_start_recording` and the quit confirm handlers
   (`_confirm_recording_quit`, `_confirm_files_quit`) `await
   asyncio.to_thread(...)` inside the action, which blocks the app message
   queue. Run that work as a Textual worker, and show "starting..." or
   "saving..." at once. Do the same for `cli/live/app.py` `action_stop`.
   Note: task 58 (diarization, in repair) also changes `cli/live/app.py` and
   its evidence says its stop job already runs outside the action handler.
   Do the hub part first. For the live part: if 58 has landed on `dev`,
   merge `origin/dev` and fix only what is left, with the test. If 58 has
   not landed when you reach it, commit the hub part, push, and report to
   the manager with `hive inbox send --to manager-stenographer`, then wait.
2. `cli/hub/dialogs.py` `QuitConfirm`: `ctrl+c` and `q` confirm, so
   `ctrl+c` twice (or `q` twice) quits while recording, after the save.
3. Correct `.hive/spec/stenographer-hub/README.md`: remove the input-first
   rule text (about lines 48 to 52) and the pending fix row (about line 89).
   Add one row for this task (`72-tui-input-first`) that describes the
   narrowed fix.
4. Tests (Textual pilot, fake services): for each of 1 and 2, a test that
   fails at base (show it). For 1: while a fake slow start or stop blocks on
   an event, the state text shows at once and another key (for example a
   section key) is handled. For 2: in the prompt, `ctrl+c` and `q` confirm.

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
- Evidence in `.hive/spec/stenographer-hub/tasks/<task-id>/evidence/`
  (feature task; the spec README is `.hive/spec/stenographer-hub/README.md`). Never put transcript
  text or audio in evidence, logs or history. Counts and timings are fine.
- No tautological tests. Mock only external dependencies. Each new
  regression test fails at base (show it), then passes.
- Do not open the microphone, capture audio, run `live` or `run`, download a
  model, or run integration tests. The user does those on the real machine.
- Do not push `dev` or `main`, open a pull request, or run a workflow.
- Gate before `hive task complete`, with zero failures:

  ```sh
  .venv/bin/ruff check .
  .venv/bin/ruff format --check .
  .venv/bin/pytest -m "not integration"
  .venv/bin/stenographer --help
  ```
