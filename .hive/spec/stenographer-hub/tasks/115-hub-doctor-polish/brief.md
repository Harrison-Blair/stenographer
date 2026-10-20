# Task: hub-doctor-polish — close the Doctor and Setup form gaps left by task 112

| Item | Value |
| --- | --- |
| Tier | decent |
| Depends on | 112 (hub-setup-doctor-board) |

## Overview

Task 112 landed the Setup and Doctor layout. Its verifier recorded form
differences from the approved boards as later polish
(`.hive/spec/stenographer-hub/tasks/112-hub-setup-doctor-board/evidence/VERIFIED.md`,
"Manager observations"). Close them. The no-background rule (task 107)
still overrides every board fill. Colour is never the only signal: the user
is colourblind, so glyphs and words carry every state; colour adds to them.

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

1. Doctor check glyphs coloured by state: ok ✓ green, warn ! warn colour,
   fail ✗ error colour. Rows stay `glyph label · detail`.
2. Selected-issue panel as on the board: border in the issue's state colour,
   a bold state-coloured title naming the problem (e.g. `overlay
   unavailable`), then one line holding the detail and the fix. Drop the
   `WARN · … / Detail: / Fix:` form.
3. The selected check row shows `! label · detail` once; it must not repeat
   the detail (task 112's capture showed `no X display · No X display.`).
   Find whether the repeat comes from the view or only from the fixture,
   and fix whichever it is.
4. Recent-warnings lines as on the board: dim `HH:MM:SS`, the level word in
   its state colour (`WARN`, `ERROR`), then the event. Drop the logger
   name. Keep the safe-warning content rules (never transcript text).
5. Setup hotkey detail (gap U-3 form): mode as the three choices with the
   current one bold accent, the test status at the bottom of the panel, as
   on the board. The capture target may stay a text row.
6. Capture fixtures use realistic, distinct labels and details, so evidence
   does not show duplicates that the real view would not produce.
7. Keep every existing key, behaviour and test.
8. Evidence: before and after renders (SVG, text, PNG) of Doctor and Setup
   at about 150x45 cells in a pilot with fake services; tests for each item
   that fail at base; `visual-check.md` per the visual check rule.
9. Verification (for the verifier): re-render, compare with the board PNGs
   by path, item by item; confirm no painted background.

Evidence folder for this task: `.hive/spec/stenographer-hub/tasks/115-hub-doctor-polish/evidence/`
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
