# Task: files-engine — file transcription jobs with progress

| Item | Value |
| --- | --- |
| Tier | decent |
| Depends on | 04, 05 |

## Overview

Decision 6. Today `stenographer transcribe` (`cli/transcribe/handler.py`)
reads the whole file, runs one recognition and prints text. Build a job
engine in a new `lib/files/` package for the Files screen. Keep the
`transcribe` subcommand behaviour unchanged.

## Requirements

1. Input: the formats `soundfile` reads (WAV, FLAC, OGG, MP3 and the rest
   of `soundfile.available_formats()`) through `soundfile`. M4A/AAC and any
   other format soundfile cannot read go through ffmpeg (user decision on
   2026-10-19).
   Choice: the system `ffmpeg` binary through a pipe (`ffmpeg -nostdin -i
   PATH -f f32le -ac 1 -ar 16000 -`, no shell), not a bundled library such
   as PyAV. Reasons: PyAV wheels bundle their own FFmpeg libraries, which
   adds tens of MB and a second licence set to the PyInstaller bundle and
   the allowlists; the system binary is in every Linux distribution
   (`/usr/bin/ffmpeg` on the user's machine); and a missing binary can be
   reported by Doctor and in the Files screen. State this choice and its
   reason in the commit message. Put the native call behind a contract in
   `lib/platform/` (AGENTS.md). Durations for the browser come from
   `soundfile.info` or `ffprobe`. When ffmpeg is missing, an M4A file shows
   "needs ffmpeg" and the job does not start. Tests use a fake `ffmpeg`
   executable on PATH that writes known float32 samples; a test with the
   real binary is an integration test.
2. A job: decode, resample to 16 kHz mono, split into phrases with the live
   VAD, transcribe each phrase with the shared ASR settings, optionally
   diarize (speaker count auto or fixed, reusing the batch pass of task 05),
   optionally refine, and save through the shared exporter (task 04) in the
   chosen formats to the chosen folder (default
   `$XDG_DATA_HOME/stenographer/files/`).
3. Progress events: stage (transcribe, diarize, save), percent, ETA, and
   completed lines for a preview. Cancel stops the job at the next phrase
   and leaves no partial output file.
4. One job runs at a time (decision 13). A queue keeps the rest. Jobs run in
   the background, in the ASR child process.
5. Tests: short synthetic audio files, a fake recogniser at the process
   boundary, cancellation, queue order, export content.

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

## Task numbers in these briefs

01 = 54-remove-windows, 02 = 55-asr-bench, 03 = 56-asr-defaults, 04 = 57-sessions-store, 05 = 58-diarization, 06 = 59-files-engine, 07 = 60-hub-shell, 08 = 61-hub-live, 09 = 62-hub-files, 10 = 63-hub-sessions, 11 = 64-hub-config, 12 = 65-hub-setup-doctor, 13 = 66-hub-docs-acceptance. Task 38 and task 45 are earlier landed tasks.
