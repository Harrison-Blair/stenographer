# Task: hub-board-audit — compare each hub screen with its approved board

| Item | Value |
| --- | --- |
| Tier | decent |
| Depends on | the hub goal tasks, all landed on dev (6e80174) |
| Kind | read-only audit: change no source, test or doc file |

## Overview

The user installed the hub from dev 6e80174 and found that the Live screen
does not match the board they approved, and that other screens diverge too.
The approved boards are HTML mockups outside the repository. Read them by
these absolute paths (do not copy them into the repository):

| Screen | Board |
| --- | --- |
| Shell, overall look, Live (mixed) | `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/StenoB.dc.html` |
| Live split view | `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/LiveSplit.dc.html` |
| Files | `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/Files.dc.html` |
| Sessions | `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/Sessions.dc.html` |
| Config | `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/Config.dc.html` (its two profile columns are out of date: one column of ASR settings, decision 15) |
| Setup | `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/Setup.dc.html` |
| Doctor | `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/Doctor.dc.html` |

The boards set layout and content (panels, their order and placement,
labels, columns, what each panel shows, key hints), not exact colours,
sizes or fonts.

A new user rule overrides every board: **no painted backgrounds.** No widget
or screen paints a background colour; the terminal background shows
through. The selected item is accent bold text with a '▶' marker, with no
fill block. Normal text uses the terminal default foreground. Borders, text
and accent colours stay. Where a board paints a fill (for example the
selected sidebar row), record it as "board fill, overridden by the
no-background rule", not as a gap.

## Requirements

Evidence folder for this task: `.hive/spec/stenographer-hub/tasks/106-hub-board-audit/evidence/` (this overrides the `evidence/<task-id>/` line in the common rules).


1. Render every hub section in a Textual pilot with fake services, at a
   board-like size (about 150x45 cells): Live idle, Live recording with a
   few fake transcript lines and meters, Live split view, Files with a
   queued and a running job, Sessions with two sessions and a selected
   detail, Config, Setup, Doctor with an ok, a warning and a failure. Use
   only fakes: no microphone, no system capture, no model load, no
   `live`/`run`. Save each render as SVG (`app.save_screenshot`) and as
   plain text into the task evidence folder.
2. For each screen, write `gaps.md` in the evidence folder: one table per
   screen with columns: board element, board (what it shows and where),
   hub now, gap (missing / different / extra / ok), and a severity (layout,
   content, key hint, cosmetic). Cite the code location (`file:line`) of
   the hub widget for each gap.
3. List every place that paints a background today (CSS `background`,
   `Screen` and `App` defaults, `$`-variables such as `$surface` or
   `$panel`, `Rich` styles with `on <colour>`, `reverse`), with
   `file:line`, in a separate section of `gaps.md`.
4. End `gaps.md` with a proposed fix split: one task per screen (Live
   first), each with its gap IDs, and say which gaps depend on the
   no-background task.
5. The renders and `gaps.md` are the only files you add. Commit them with
   `git add -f`, gate, push the task branch, `hive task complete`.

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
