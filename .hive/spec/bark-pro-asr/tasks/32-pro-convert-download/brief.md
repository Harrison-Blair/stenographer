# Task: pro-convert-download — convert and install Bark Pro with `model download --asr`

| Item | Value |
| --- | --- |
| Tier | strong |
| Feature | bark-pro-asr |
| Depends on | 31-bark-pro-spec (landed) |

## Overview

The design authority is `.hive/spec/bark-pro-asr/README.md` on dev. Read it in
full. This task is spec task A: the converter asset, the pins module, the
download, the free-space and venv checks, the Doctor venv warning, the manifest,
and `is_model_cached`. Follow the spec's Contracts sections "Model directory",
"Converter" and "Download" exactly. Do not start task B or C work: the Whisper
backend and the Whisper config keys stay in place in this task, and the app must
still run as today.

## Requirements

1. Converter asset `src/stenographer/assets/convert/bark_pro_to_sherpa.py`, from the
   task 26 basis, with the spec's changes (fixed seeds and threads, metadata
   comment, the graph check is an error) and exit codes 0-4. Add it to the Git and
   build allowlists (docs/building.md).
2. One pins module in `lib/transcribe/` (you name it): source repo and revision,
   source-file sha256, exact package versions (torch CPU, transformers, onnx,
   onnxruntime, numpy; they need wheels for the system python3 3.12), and the
   output sha256 values.
3. `stenographer model download --asr`, in the spec's check order: the venv check
   (decision: `python3 -m venv` must work, else print
   `sudo apt install python3-venv` and stop with a non-zero exit, before any
   network call), free space (6 GiB), the temp venv with the system python3, pinned
   installs with `--no-cache-dir` (no wheel cache may remain in ~/.cache/pip),
   source download over pinned HTTPS URLs with urllib and sha256 checks, the
   converter run, the output sha256 check (fail closed), atomic install with
   `os.replace`, manifest, NOTICE and LICENSE, then cleanup of the venv and the BF16
   source on success and on failure. Also fetch `silero_vad.onnx` through the
   existing live download path. Print the attribution line. A present model with a
   matching manifest is not rebuilt.
4. `is_model_cached()` per the spec (manifest check, no hashing).
5. Doctor: a warning when `python3 -m venv` would fail, with the apt fix. The
   Setup models step uses the new download.
6. Tests: failing-first unit tests for the pure logic (manifest parse and
   `is_model_cached`, check order, free-space rule, each converter exit-code
   message, sha mismatch fails closed and installs nothing, cleanup on failure,
   the atomic install). Inject seams for subprocess and network; no OS-call mocking
   beyond those seams.
7. Evidence, from real runs on this machine (user-approved: two real conversions
   in scratch):
   - Run the conversion twice and show identical output sha256 for all four files.
     Pin those values. If the two runs differ, STOP and send the manager the
     differing files and your diagnosis; do not pin anything.
   - One real `stenographer model download --asr` run end to end with
     `XDG_DATA_HOME` pointing at a scratch dir in your worktree (never the user's
     real data dir). Show the output, the installed tree with sizes, the manifest,
     and that the venv, the BF16 source and the build dir are gone. Show
     `du -sh ~/.cache/pip` before and after (it must not grow by the wheel sizes).
   - Record wall time, peak disk use and peak RSS of the conversion.
   - Delete every scratch model, venv and download after the evidence is recorded.

Evidence folder: `.hive/spec/bark-pro-asr/tasks/32-pro-convert-download/evidence/`.

## Rules

- Follow the repository AGENTS.md. Linux only. Keep the headless core.
- Your worktree has no `.venv`. Agents never create the repo venv with pyenv
  Python: ask the user (through the manager) to run
  `! python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'` in your pane, and
  wait. The temporary conversion venv made by the product code with the system
  python3 is allowed (it is the product behaviour under test).
- Never run sudo. Never run git stash (stash@{0} is the user's WIP).
- Model downloads are allowed only as described in requirement 7. Do not open the
  microphone, run `live` or `run`, or run integration tests.
- No transcript text or audio in logs, evidence or history.
- Never signal a process or close a pane you did not start. Never work in wBC.
- Do not push dev or main, open a PR, or run a workflow. Conventional commits, no
  attribution trailers. Evidence committed with `git add -f`.
- Gate before `hive task complete`, zero failures:
  `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`,
  `.venv/bin/pytest -m "not integration"`, `.venv/bin/stenographer --help`.
