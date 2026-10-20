# Task: hub-setup-doctor-board — match Setup and Doctor to the approved boards

| Item | Value |
| --- | --- |
| Tier | decent |
| Depends on | 106 (board audit) and 107 (no backgrounds), and the Live task (hub-live-board) for the sidebar card mechanism |

## Overview

The user found that the hub screens do not match the boards they approved.
Task 106 audited them; its gap list is `.hive/spec/stenographer-hub/tasks/106-hub-board-audit/evidence/gaps.md` (on dev). Fix these gaps: U-1, U-3, D-1 to D-4.
Read the approved board(s) by absolute path; never copy them into the
repository (it is public):

- `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/Setup.dc.html`
- `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/Doctor.dc.html`

The boards set layout and content (panels, order, placement, labels,
columns, what each panel shows, key hints), not exact colours, sizes or
fonts. The no-background rule (task 107) overrides every board fill: no
painted background anywhere; selected item = bold accent text with a `▶`
marker; normal text = terminal default foreground. Keep task 107's
no-background test passing.

## Design

| Board | Source | PNG |
| --- | --- | --- |
| Setup | `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/Setup.dc.html` | `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/Setup.png` |
| Doctor | `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/Doctor.dc.html` | `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/Doctor.png` |

## Visual check (user-approved rule, 2026-10-20)

Worker: capture each changed screen and each board as PNG, compare them,
and fix the gaps before you finish. Verifier: re-capture both independently
and judge.

- Board PNG: already rendered, cite by path (above). To re-render:
  `firefox --headless --no-remote --profile <scratch dir> --window-size=1220,780 --screenshot out.png file://<board>.dc.html`.
- Textual screen: pilot `app.save_screenshot()` SVG, then
  `rsvg-convert -o out.png in.svg`.
- Any terminal pane: `herdr pane read <your own pane> --source visible --format ansi > f.ansi`,
  convert the ANSI SGR to an HTML `<pre>` with a short script in your
  scratch dir, then the firefox screenshot.
- Evidence: commit the screen PNGs to the task evidence folder. Board PNGs
  stay in the hive home under `.hive/tmp/`; cite them by path. Never commit
  a board or a board image to the repository (it is public).
- Report: `visual-check.md` in the evidence folder, a table with one row per
  board element: matches / differs (reason) / overridden (the decision that
  overrides it, e.g. the no-background rule).
- Capture only your own panes or a scratch run (ownership rule).

## Requirements

1. Setup: a bordered step list on the left and a bordered detail panel for the selected step on the right. The hotkey step detail shows capture target, mode, hybrid threshold, general binding, cancel binding, device and test status.
2. Doctor: summary card in the sidebar (counts and check time); two check groups side by side; a bordered detail/fix panel for the selected issue; a bordered recent-warnings log panel.
3. Keep every existing key, behaviour and test (model download needs confirm; optional warnings do not change the doctor exit code).
7. Evidence: before and after renders (`app.save_screenshot` SVG and plain
   text) of each changed screen at about 150x45 cells, rendered in a pilot
   with fake services, plus a table mapping each gap ID to the fix and its
   test. Pilot tests assert the new structure (panels present, bordered,
   placed as on the board) and fail at base.
8. Verification (for the verifier): re-render each screen and compare it
   with the board by absolute path, gap by gap; confirm no painted
   background.

Evidence folder for this task: `.hive/spec/stenographer-hub/tasks/112-hub-setup-doctor-board/evidence/`
(this overrides the `evidence/<task-id>/` line in the common rules).

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
