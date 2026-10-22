# Task: docs-notice-fixmd — document Bark Pro, credit the models, add FIX.md

| Item | Value |
| --- | --- |
| Tier | decent |
| Feature | bark-pro-asr |
| Depends on | 32, 44, 48 (all landed; dev 1cf20f2) |

## Overview

The design authority is `.hive/spec/bark-pro-asr/README.md` on dev. Read it in full,
especially Decisions, the Attribution contract, and Limits. This is spec task D, the
last task. Bark Pro (int8, sherpa-onnx, CPU) now replaces Whisper in dictation, live
and Files. Users run `stenographer model download --asr` once. Code is done; change
code only where a user-visible string is wrong, and ask the manager first.

## Requirements

1. Attribution files in `src/stenographer/assets/licenses/` per the spec:
   `underdog-bark-3.0-pro-NOTICE.txt` (the ConwayResearch NOTICE verbatim, the CC-BY-4.0
   link, and the modification line), and license notes for Silero VAD (MIT) and TitaNet
   (its NeMo license). Take the NOTICE text from the pinned revision's NOTICE file
   (the task 32 converter installs a copy as `NOTICE`; the pins module names the source
   URL and sha256). Fetching that one small text file at the pinned revision is
   allowed; check its sha256 against the pin. Keep the Git and build allowlists in sync.
2. README: a "Third-party models" section under "License" with model, authors, license
   and link for Underdog Bark 3.0 Pro (Conway Research), nvidia/parakeet-tdt-0.6b-v3,
   moondream/parakeet-ultra (named in the Bark NOTICE), Silero VAD and TitaNet. Update
   the install and model sections: `model download --asr` converts on your machine; the
   one-time prerequisite `sudo apt install python3-venv`; needs 10 GiB free disk and
   about 10.2 GiB RAM during conversion; about 2 minutes on the test machine; CPU only.
3. Docs: update `docs/usage.md`, `docs/live.md`, `docs/hub.md`, `docs/refine.md`,
   `docs/building.md` and any other owning doc that names Whisper, CUDA/cuDNN needs for
   ASR, or a removed config key (`model`, `compute_type`, `beam_size`, `hotwords`,
   `initial_prompt`, `vad_filter`, `silence_threshold`). Old keys in a user's config are
   ignored. Keep `docs/transcription-experiments.md` as history; add one dated note at
   its top that the app now uses Bark Pro (link the task 26 report).
4. Site (`site/`): update the copy that names Whisper or the old model. Site copy speaks
   to the reader in the second person ("your machine", "your cursor"). Run
   `scripts/check_site.sh`.
5. CHANGELOG: an upcoming (unreleased) entry: breaking change, Bark Pro replaces Whisper
   in every mode, the removed keys, the new download and its prerequisite, fillers stay,
   and the removed bench and study scripts.
6. `FIX.md` at the repo root: a short handoff prompt the user pastes into a coding agent
   on each machine after updating to this dev. It tells the agent to:
   - ask the user to run `sudo apt install python3-venv` (the agent never runs sudo),
     and check it with `python3 -c 'import ensurepip'`;
   - update the app (`scripts/reinstall.sh` in a checkout), then run
     `stenographer model download --asr` (state the disk and RAM needs) and
     `stenographer doctor`;
   - show the user the now-ignored Whisper keys in their config and remove them only
     with the user's consent, through a normal edit (they are harmless if left);
   - ask the user before deleting the old Whisper model cache (name the likely path
     under `~/.cache/huggingface/hub/` for `deepdml/faster-whisper-large-v3-turbo-ct2`,
     and tell the agent to show its size first);
   - never open the microphone or test dictation without the user's consent.
   Say at its top that it is temporary and a later commit deletes it.
7. Every user-visible statement must match the code on dev. Check each command and
   flag you document with `stenographer ... --help`.

Evidence folder: `.hive/spec/bark-pro-asr/tasks/54-docs-notice-fixmd/evidence/`. Include a grep
showing no Whisper or removed-key reference remains in README, docs (except
transcription-experiments history and the CHANGELOG history), and site.

## Rules

- Follow the repository AGENTS.md. Write plainly, in short sentences.
- Your worktree has no `.venv`. Agents never create the repo venv: send the manager a
  request through `hive inbox send --to manager-stenographer` so the user runs
  `! python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'` in your pane, and wait
  for the gate. Write docs meanwhile. Ask all questions through the inbox; the manager
  does not read your pane.
- Never run sudo. Never run any git stash command (stash@{0} is the user's WIP).
- No model download (except the one NOTICE text file in requirement 1), no
  microphone, no `live` or `run`, no integration tests.
- No transcript text or audio anywhere.
- Never signal a process or close a pane you did not start. Never work in wBC.
- Do not push dev or main, open a PR, or run a workflow. Conventional commits, no
  attribution trailers. Evidence committed with `git add -f`.
- Gate before `hive task complete`, zero failures, in the worktree `.venv`:
  `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`,
  `.venv/bin/pytest -m "not integration"`, `.venv/bin/stenographer --help`, and
  `scripts/check_site.sh`. Known timing flakes: tests/cli/hub/test_sessions.py::test_session_playback_toggles_and_jobs_run_without_blocking_navigation
  and tests/cli/hub/test_app.py::test_pilot_lifecycle_worker_finishes_after_hub_screen_unmount_without_failure;
  if one fails, rerun it alone 5 times and record that.
