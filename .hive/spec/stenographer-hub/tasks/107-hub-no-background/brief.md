# Task: hub-no-background — no painted backgrounds in the hub or live

| Item | Value |
| --- | --- |
| Tier | decent |
| Depends on | the hub goal tasks, all landed on dev (6e80174) |
| Scope | the hub (`cli/hub/`) AND `stenographer live` (`cli/live/`) |

## Overview

User rule (2026-10-20): remove every painted background. The terminal's own
background must show through every screen, panel, dialog and widget of the
hub and of `stenographer live`. Task 106 (running in parallel) audits the
screens against the boards; this task changes only colours and the selected
-item style, not layout or content.

Approved look (for accent colours and borders only; ignore the boards'
background fills): `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/StenoB.dc.html` and `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/LiveSplit.dc.html`. Read
them by these absolute paths; never copy them into the repository.

## Requirements

1. No widget, screen, dialog, App default or Rich style paints a background:
   no CSS `background` other than `transparent`, no `$surface`, `$panel`,
   `$boost` or similar fills, no `on <colour>` Rich styles, no `reverse`.
   Override Textual's default component backgrounds (Screen, Header,
   Footer, DataTable cursor and header, ListView/OptionList highlight,
   Input, Button, ModalScreen dim, scrollbars, tooltips) as needed. Use the
   terminal's colours (`App.ansi_color = True` if that is the cleanest way;
   check that it does not break the accents) so the terminal default
   background and foreground apply.
2. Keep borders, text and the accent colours. Normal text uses the
   terminal default foreground.
3. A selected or highlighted item (sidebar section, list rows, table
   cursor, option lists, Config rows, Setup steps, Doctor checks, Sessions
   list, Files browser and queue, live speaker picker) shows accent bold
   text and a '▶' marker, with no fill block. Focus remains visible
   without a fill (border accent or the marker).
4. Tests: a pilot test renders every hub section (Live idle and recording,
   split, Files, Sessions, Config, Setup, Doctor, the quit and other
   dialogs) and the `live` app, and asserts that no rendered segment has a
   background colour other than none/default. It fails at base (show it).
   Another test asserts the '▶' marker and bold accent on the selected
   sidebar row and on one list's selected row.
5. Evidence: before/after SVG renders (`app.save_screenshot`) of Live and one
   list screen in the task evidence folder.

Evidence folder for this task: `.hive/spec/stenographer-hub/tasks/107-hub-no-background/evidence/`
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
