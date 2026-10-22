# Task: asr-config-cleanup — remove Whisper from config, dependencies and scripts

| Item | Value |
| --- | --- |
| Tier | decent |
| Feature | bark-pro-asr |
| Depends on | 44-bark-asr-backend (landed, dev 9f77deb) |

## Overview

The design authority is `.hive/spec/bark-pro-asr/README.md` on dev. Read it in full.
This is spec task C. Follow the Contracts section "Config" exactly. After task 44 the
backend decodes with Bark Pro, and no module under `src/` imports faster_whisper.
This task removes what is left of Whisper. Do not change docs, README or site
(task D), except that comments and docstrings in changed code must stay true.

## Requirements

1. `AsrConfig` has only `idle_unload_seconds` and `cpu_threads`. `_build_asr` reads only
   those keys, with the current ranges. Remove `model`, `compute_type`, `beam_size`,
   `hotwords`, `initial_prompt`, `vad_filter`, `silence_threshold` and
   `ALLOWED_COMPUTE_TYPES` from config models, validation, constants and
   `assets/default_config.toml.in` (keep `[stenographer.asr]` with the two keys).
2. Old configs: a config file that holds any removed key loads without error and
   without a warning. Saves go through the preservation layer and keep the user's old
   keys in place. Failing-first tests prove both (load an old full Whisper config;
   save a change and show the old keys survive byte-for-byte).
3. Remove every surface that shows or uses a removed key: the hub Config board rows
   (`cli/hub/config_view.py`, `cli/hub/app.py`), the run banner, the setup workflow,
   analytics, diagnostics context and session, `lib/live/live_session.py`, and shell
   completions. The Setup and Doctor model rows name the Bark model. Text-only screen
   changes; no board needed (spec decision 12).
4. Dependencies: remove faster-whisper and huggingface_hub from `pyproject.toml`
   (all extras), and any CTranslate2 handling. `packaging/stenographer.spec` no longer
   collects data from faster_whisper; the Silero onnx comes from the pinned live model
   download, so check that nothing in the bundle still expects a bundled Silero file
   (grep, then explain in the evidence).
5. Delete `lib/transcribe/download.py` and its tests (its callers moved in task 44).
6. Delete (user decisions 2026-10-21 and Q11 2026-10-22): `scripts/live_bench.py`,
   `scripts/transcription_study/decode.py`, `real_audio.py`, `asr_grid.py`,
   `download_models.py`, and their tests. Keep the other study modules only if their
   tests pass without these files; if a kept module (for example `profiles.py`) refers
   to Whisper options, remove only those references, or ask the manager if the
   module has no purpose left.
7. Free space: raise the `model download --asr` minimum from 8 GiB to 10 GiB in code,
   its test and the spec's Download section (real peaks: 6.91 GiB and 7.52 GiB).
8. Gate extra (spec): `grep -rn "faster_whisper\|faster-whisper\|ctranslate2\|huggingface_hub"`
   over `src/`, `tests/`, `packaging/` and `pyproject.toml` finds nothing, except
   `src/stenographer/assets/convert/constraints.txt` (manager decision 2026-10-22: it is the
   sha256-pinned lock of the temporary converter venv; transformers needs huggingface_hub
   there, and changing it would void the task 32 output pins). Show also that
   `grep -rn "compute_type\|beam_size\|hotwords\|initial_prompt\|vad_filter\|silence_threshold"`
   over `src/` finds nothing, and over `tests/` finds only the old-config tests.
9. Build check: run the existing allowlist check (docs/building.md) if there is one.
   Do not build a PyInstaller bundle unless docs/building.md requires it for a spec
   change; ask the manager first.

Evidence folder: `.hive/spec/bark-pro-asr/tasks/48-asr-config-cleanup/evidence/`.

## Rules

- Follow the repository AGENTS.md. Linux only. Keep the headless core. Preserve
  configuration compatibility.
- Your worktree has no `.venv`. Agents never create the repo venv: ask the manager to
  have the user run `! python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'`
  in your pane, and wait for the gate. Write code meanwhile. Note that the venv
  created after your pyproject change will not have faster-whisper; that is correct.
- Ask questions through `hive inbox send --to manager-stenographer`, not only in your
  pane; the manager does not read your pane.
- Never run sudo. Never run any git stash command (stash@{0} is the user's WIP).
- No model download, no microphone, no `live` or `run`, no integration tests.
- No transcript text or audio in logs, history, analytics or evidence.
- Never signal a process or close a pane you did not start. Never work in wBC.
- Do not push dev or main, open a PR, or run a workflow. Conventional commits, no
  attribution trailers. Evidence committed with `git add -f`.
- Gate before `hive task complete`, zero failures, in the worktree `.venv`:
  `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`,
  `.venv/bin/pytest -m "not integration"`, `.venv/bin/stenographer --help`.
  Known timing flakes: tests/cli/hub/test_sessions.py::test_session_playback_toggles_and_jobs_run_without_blocking_navigation
  and tests/cli/hub/test_app.py::test_pilot_lifecycle_worker_finishes_after_hub_screen_unmount_without_failure.
  If one fails, rerun it alone 5 times and record that.
