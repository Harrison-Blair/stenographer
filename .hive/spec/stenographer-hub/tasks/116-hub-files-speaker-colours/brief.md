# Task: hub-files-speaker-colours — distinct speaker colours in the Files preview

| Item | Value |
| --- | --- |
| Tier | decent |
| Depends on | 109 (hub-files-board) |

## Overview

Task 109 landed the Files board. In its after-render every speaker label in
the preview panel is the same cyan, while the board gives each speaker its
own colour (Speaker 1 orange, Speaker 2 purple). Task 108 added stable
per-speaker colours to Live; Sessions uses them too. Make the Files preview
use the same per-speaker colour mechanism (reuse it; do not add a second
palette). Colour is never the only signal: the speaker name is always shown.

## Design

| Board | Source | PNG |
| --- | --- | --- |
| Files | `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/Files.dc.html` | `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/Files.png` |

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

1. Files preview speaker labels use the shared stable per-speaker colours
   (bold, no fill), consistent with Live and Sessions for the same label.
2. A failing-first pilot test asserting two speakers render with different
   styles in the Files preview.
3. Evidence: before/after Files renders (SVG, text, PNG) at about 150x45
   with synthetic text only; `visual-check.md` per the rule.
4. Keep every existing key, behaviour and test.

Evidence folder for this task: `.hive/spec/stenographer-hub/tasks/116-hub-files-speaker-colours/evidence/`
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
