# Task: hub-spec — land the stenographer-hub feature spec

| Item | Value |
| --- | --- |
| Tier | small |
| Feature | `stenographer-hub` (spec task) |
| Depends on | none |

## Overview

Hive now keeps each feature spec in the project repository at
`.hive/spec/<feature>/README.md`, with task briefs at
`.hive/spec/<feature>/tasks/<id>/brief.md` and evidence at
`.hive/spec/<feature>/tasks/<id>/evidence/` (see the hive worker skill).
The user chose on 2026-10-19 to adopt this in stenographer for the hub goal.
This task lands the spec and the allowlist so that later hub tasks can use
feature `stenographer-hub`.

## Requirements

1. `.hive/spec/stenographer-hub/README.md`: the design authority for the hub
   goal. Content, from the hive home (read these files):
   - the goal and decisions 1 to 15:
     `/home/penguin/source/hive/.hive/tmp/coordinator/goal-stenographer-hub.md`;
   - the user rule "user input is first class":
     `/home/penguin/source/hive/overrides/tui-input-first-class.md`, with the
     stenographer detail: a quit prompt only while a recording runs, and
     `ctrl+c` twice still exits;
   - the accepted assumptions (user, 2026-10-19): Files reads soundfile
     formats directly and M4A/AAC through the system `ffmpeg` binary through
     a pipe (reason: PyAV bundles its own FFmpeg libraries; the system binary
     is present and a missing one can be reported; Doctor warns when it is
     missing); recent-line context is new and ships only if the user picks
     it from the bench; the bench WER corpus download (about 1.08 GB) was
     consented once; the user's recording
     `system-audio-20261018-134825.wav` (5.65 h, 4 speakers) may be used by
     the bench and the diarization task, and is never committed with its
     text; `stenographer live` keeps its flags; the config backup is the
     timestamped `config.toml.bak-<time>`; new Doctor checks are warnings;
     playback uses `pw-play`;
   - the task table: IDs 54 to 66 with title, dependencies and status
     (landed: 54, 57, 60; running: 55, 58; the rest waiting), and the new
     input-first fix task (slug `tui-input-first`; hive gives its ID after this spec lands, so list it as pending without an ID). Tasks before this spec
     keep their evidence in `evidence/<task-id>/`; new tasks of the feature
     use `.hive/spec/stenographer-hub/tasks/<id>/`.
   - The design boards stay in the hive home
     (`.hive/tmp/coordinator/designs/stenographer/`). Name the path; do not
     copy them.
   Keep it short and factual. No transcript text.
2. Allowlist: Git must track `.hive/spec/` (and nothing else under `.hive/`).
   The build (sdist, wheel, PyInstaller) must exclude it. Follow
   `docs/building.md`: change `.gitignore` and `tool.hatch.build.exclude` in
   `pyproject.toml` together, and any allowlist test. Show with
   `git check-ignore -v` that `.hive/spec/stenographer-hub/README.md` is
   tracked and `.hive/tmp/x` is ignored, and show that a built sdist and
   wheel contain no `.hive/` path.
3. Add one line to `docs/building.md` that names `.hive/spec/` as the hive
   spec and evidence area, tracked but not shipped. Do not change
   `AGENTS.md`.
4. Evidence: `.hive/spec/stenographer-hub/tasks/<task-id>/evidence/`.

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
- Do not push `dev` or `main`, open a pull request, or run a workflow.
- Gate before `hive task complete`, with zero failures:

  ```sh
  .venv/bin/ruff check .
  .venv/bin/ruff format --check .
  .venv/bin/pytest -m "not integration"
  .venv/bin/stenographer --help
  ```

Note: requirement 4 sets the evidence path for this task. It replaces the `evidence/<task-id>/` path in the common rules. After the allowlist change, `git add -f` is not needed.
