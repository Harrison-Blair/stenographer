# Task: files-default-recordings — Files browser opens in the recordings folder

| Item | Value |
| --- | --- |
| Tier | small |
| Depends on | none |

## Overview

The user usually opens a live recording from the Files board. Today the
Files browser (`src/stenographer/cli/hub/files_view.py`, `FilesPanel.__init__`)
starts at `Path.home()`. Live sessions are saved under
`<data_dir>/sessions/<UTC stamp>/` (`mic.flac`, `system.flac`), where
`data_dir` comes from `platform.data_dir(os.environ, Path.home())`
(`$XDG_DATA_HOME/stenographer` or `~/.local/share/stenographer`).

## Decisions (user, 2026-10-21)

1. The Files browser opens in `<data_dir>/sessions` by default.

## Design

No approved board. User waiver, 2026-10-21 (through the coordinator), for
tasks 24 and 25 only: this change does not alter a layout, so the
approved-board comparison is waived. The verifier's independent before and
after renders of each changed screen (pilot `save_screenshot()` SVG, text and
PNG, synthetic data only) count as the visual approval. Keep those renders in
the evidence. The plain-text check still applies: each state must have a glyph or
word and must not rely on colour alone. Future UI tasks still need an approved board.

## Requirements

1. The browser's start directory is `<data_dir>/sessions`, resolved through the
   platform `data_dir` (as `HubServices` already does for `files_output_folder`;
   see `cli/hub/services.py` and the `files_home` wiring in `cli/hub/app.py`).
   Respect `XDG_DATA_HOME`.
2. If that folder does not exist (or is not a directory), fall back to the home
   folder. Do not create the folder.
3. The user can still navigate up with `..` from the start folder (no root lock).
   The browser title shows the current folder sensibly when it is not under home.
4. The output-folder default stays `<data_dir>/files`. It must not be derived
   from the new start folder (today `files_view.py` derives a fallback from `self.home`).
5. Failing-first tests: start folder is the sessions dir when it exists (with
   `XDG_DATA_HOME` pointed at a tmp dir), falls back to home when absent, and
   the output folder default is unchanged.
6. Docs: `docs/hub.md` Files section, README if it describes Files, and `site/`
   if it describes Files.
7. Evidence: one before/after Files render (pilot `save_screenshot()` SVG plus
   text, synthetic data only) and the failing-first run.

Evidence folder: `.hive/spec/stenographer-hub/tasks/24-files-default-recordings/evidence/`.
## Common rules

- User decisions, 2026-10-21 (through the coordinator): the decisions in this
  brief are final. They extend the hub spec `.hive/spec/stenographer-hub/README.md`.
- Grant: `grants.md 2026-10-21 stenographer delivery on dev` (merge to `dev` only, never `main`).
- Follow the repository `AGENTS.md`. Linux only. Keep the headless core: the
  daemon and every existing subcommand keep their behaviour.
- User-facing changes update README.md, the owning docs, and the Pages site
  (`site/`). The primary checkout has uncommitted user edits in README.md,
  docs/usage.md, pyproject.toml and site/index.html. Never touch that checkout;
  work only in your task worktree.
- Evidence in the evidence folder named below, committed with `git add -f`.
  Never add evidence paths to `.gitignore` or `pyproject.toml`. Never put
  transcript text or audio in evidence, logs or history. Counts and timings are fine.
- No tautological tests. Mock only external dependencies. Each new
  regression test fails at base (show it in evidence), then passes.
- Do not open the microphone, capture audio, run `live` or `run`, download a
  model, or run integration tests. The user does those on the real machine.
- Never signal a process or close a tab, pane or workspace that you did not
  start. Never work in workspace wBC (the hive session).
- Do not push `dev` or `main`, open a pull request, or run a workflow.
- Commits: conventional commits, no attribution or Co-Authored-By trailers.
- Gate before `hive task complete`, with zero failures:

  ```sh
  .venv/bin/ruff check .
  .venv/bin/ruff format --check .
  .venv/bin/pytest -m "not integration"
  .venv/bin/stenographer --help
  ```
