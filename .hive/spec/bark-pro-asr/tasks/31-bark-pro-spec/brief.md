# Task: bark-pro-spec — design authority for the Bark Pro ASR swap

| Item | Value |
| --- | --- |
| Tier | small |
| Kind | spec (docs only) |
| Depends on | none |

## Overview

Write `.hive/spec/bark-pro-asr/README.md`, the design authority for the
feature `bark-pro-asr`. Later tasks (A convert/download, B backend, C config
cleanup, D docs) read it as their contract. Change no other file.

Sources: the user-approved plan
`/home/penguin/source/hive/plans/stenographer/bark-pro-integration.md` (read it in full) and the
task 26 report `.hive/spec/stenographer-hub/tasks/26-bark-eval/evidence/report.md`
on dev (technical facts, the converter basis `evidence/bench/export_pro_sherpa.py`,
Pro revision `4b5c51e04aa8d16dda9ecdff71bc29f7360149e4`).

## Decisions to record (user, 2026-10-21)

1. Pro only: Underdog Bark 3.0 Pro, int8, sherpa-onnx, CPU. It replaces Whisper in
   dictation, live and Files. faster-whisper leaves the project completely
   (code, pyproject, packaging, tests). Remove the Whisper keys `compute_type`,
   `beam_size`, `hotwords`, `initial_prompt`, `vad_filter`, `silence_threshold`,
   and `model`. Keep `idle_unload_seconds` and `cpu_threads`. Breaking change. No Clean.
2. Model source: one-time local conversion of the official ConwayResearch Pro
   weights, pinned by revision. No hosting, no publishing.
3. `stenographer model download --asr` creates a temporary venv with the system
   Python 3, installs pinned CPU-only torch and pinned transformers, onnx, onnxruntime,
   and numpy, downloads Pro at the pinned revision and checks the source-file sha256,
   converts, checks the output sha256, installs, then deletes the venv and the BF16
   source. It checks free disk space first (about 4-5 GB temporary). Keep only the
   int8 encoder/decoder/joiner, tokens.txt, NOTICE, LICENSE and a manifest.
4. Output sha256 mismatch: fail closed with a clear message. Task A converts twice on
   this machine first to prove that the output is deterministic. If it is not, the
   manager returns to the user with a fallback (functional check on a synthetic clip).
5. Silence: dictation runs the live-mode Silero VAD before the decode, with 0.25 s
   pre-pad. Empty results are dropped. No confidence threshold. The no_speech_prob
   gates are removed (decode.py, live_session.py). `--asr` also fetches the pinned
   silero_vad.onnx (the existing live model entry), so dictation needs only `--asr`.
6. Old config keys: no automatic rewrite; the loader ignores unknown and removed keys.
7. Fillers stay in every mode. Refine cleans dictations of 10 or more words (unchanged).
8. `FIX.md` at the repo root on dev: a short handoff prompt for a coding agent on each
   machine (update config, run the model download, ask the user before deleting the
   old turbo cache). A later commit deletes it once both machines are done.
9. Delete `scripts/transcription_bench.py`, `scripts/live_bench.py` and their tests.
10. Attribution: NOTICE in `assets/licenses/`, a README "Third-party models" section,
    and a line in the download output. Credit Bark/ConwayResearch (CC-BY-4.0, note
    the int8 conversion as a modification), nvidia parakeet-tdt-0.6b-v3, Silero VAD,
    and TitaNet.
11. Land on dev under the grant 2026-10-21. No main PR, no release.
12. No approved board is needed for text-only screen changes (Config rows, banner).

## Q1 decided (user, 2026-10-21): venv source

- Prerequisite: the Ubuntu package `python3-venv` (`sudo apt install python3-venv`),
  once on each machine. Agents never run sudo; the user runs the apt step.
- `model download --asr` first checks that `python3 -m venv` works. If it does not,
  it prints that fix and stops (non-zero exit, nothing downloaded).
- Doctor warns when `python3 -m venv` would fail.
- FIX.md names the apt step for the user to run.

## Contracts to define

- Model dir: `<data_dir>/models/asr/bark-pro-int8/` with `encoder.int8.onnx`,
  `decoder.int8.onnx`, `joiner.int8.onnx`, `tokens.txt`, `NOTICE`, `LICENSE`,
  `manifest.json` (revision, package pins, sha256 per file). `is_model_cached` checks it.
- Converter: a bundled asset script run by the temp venv's python. It must not import
  stenographer. Name its CLI (input dir, output dir) and its exit codes.
- Backend: `Model.transcribe(samples) -> TranscriptionResult` stays the caller seam.
  `SegmentInfo.no_speech_prob` is removed. Say which timestamps the result carries
  (sherpa token durations), and that live and Files keep their VAD phrase times.
- Config: the new `AsrConfig` fields, and that removed keys load without error.
- The task list S, A, B, C, D with dependencies (A after S and the user's apt step; B after A;
  C after B; D after A, B, C) and the gate per task.

## Rules

- Docs only. Commit only `.hive/spec/bark-pro-asr/README.md` and this task's
  evidence folder `.hive/spec/bark-pro-asr/tasks/31-bark-pro-spec/evidence/` (with `git add -f`).
- Write plainly, in short sentences. No transcript text.
- Do not run git stash. Do not push dev or main. Conventional commits, no trailers.
- Gate: this task changes no Python, so no venv is needed (never create one). Check
  that `git diff --name-only dev...HEAD` lists only `.hive/spec/bark-pro-asr/` paths.
