# Task: bark-eval — evaluate Underdog Bark 3.0 Pro and Clean for stenographer

| Item | Value |
| --- | --- |
| Tier | strong |
| Kind | research only |
| Depends on | none |

## Overview

The user asks (2026-10-21, through the coordinator) for an evaluation of the
Underdog Bark 3.0 speech models, mainly Pro and Clean. Research only: do not
change the stenographer transcription path or any production file. The output
is a report; the user then decides about integration.

Model card facts (ConwayResearch on Hugging Face, CC-BY-4.0, English only,
finetuned from nvidia parakeet-tdt-0.6b-v3):

- Pro: https://huggingface.co/ConwayResearch/Underdog-Bark-3.0-Pro . Verbatim.
  BF16 safetensors 1.25 GB. Loads with stock transformers `ParakeetForTDT`.
  Open ASR average WER 4.29 % (AMI 7.16).
- Clean: https://huggingface.co/ConwayResearch/Underdog-Bark-3.0-Clean . Built on
  Bark 3.0 Plus. Removes fillers, false starts, repeated words. 180 MB
  `model.bark`, 1.25 GB in memory; needs `bark_loader.py` with
  transformers>=5.19, torch, constriction. Word timestamps after cleanup are
  not documented.
- Community sherpa-onnx int8 conversion of Pro:
  https://huggingface.co/joshthomasdev/sherpa-onnx-nemo-underdog-bark-3.0-pro-int8 .
  stenographer already depends on sherpa-onnx.

Current stenographer models: ASR `deepdml/faster-whisper-large-v3-turbo-ct2`
(faster-whisper, CTranslate2; shared by dictation, live and Files), Silero VAD
and a sherpa-onnx speaker-embedding model for live/Files diarization
(`lib/live/`, `lib/files/engine.py`). Diarization assigns speakers per phrase
and uses phrase/segment timestamps; check what `lib/files/engine.py` and
`lib/live/` actually consume.

## Report items (for Pro, Clean, and the current models)

1. Runtime path in stenographer: sherpa-onnx (no new dependency) or
   transformers + torch (large new dependency; give installed size). Can Clean
   run in sherpa-onnx (check its format and the loader; say what a conversion
   would need)?
2. Fit per mode: file transcription, live phrases (latency per ~2-10 s phrase,
   model load time), dictation, and diarization (which timestamps each model
   gives: segment, word, token; whether Clean keeps usable timestamps).
3. Accuracy and speed on real audio on this machine. Hardware: record CPU
   model/cores, RAM, GPU (RTX 3080 Laptop, 8 GB, CUDA present). Measure CPU,
   and GPU where the runtime supports it: load time, real-time factor, peak RSS
   / VRAM. Use the same clips for every model. AUDIO SOURCE: see "Open
   decision" below; do not start step 3 until the manager confirms it.
4. License attribution stenographer must show for CC-BY-4.0 (and the parakeet
   base model's license), and where it would go (README, site, NOTICE, about).
5. Recommendation: which model for which mode, and the size of the
   integration work (files, dependencies, packaging/PyInstaller impact).

## Audio source (user decision, 2026-10-21)

- Speed, memory, output samples and model-to-model agreement: 2 or 3 excerpts,
  5 to 10 minutes each, of `/tmp/system-audio-20261018-134825.wav`. Cut them
  into `.scratch/audio/` in your worktree. Never commit any audio, excerpt or
  transcript of this recording. Remove the excerpts after the report.
- True WER: the cached public corpus
  `/home/penguin/source/stenographer/.cache/transcription-study-20260912`
  (see `scripts/transcription_study/`). Read it in place; do not modify it.

## Sherpa-onnx path (manager, 2026-10-21)

- `joshthomasdev/sherpa-onnx-nemo-underdog-bark-3.0-pro-int8` returns HTTP 401;
  report that it is unavailable.
- Approved: export Pro to sherpa-onnx int8 locally from the authorised Pro
  safetensors in the scratch venv (no extra model download). Report the
  conversion steps and whether the result matches the transformers output.
- velddev/Underdog-Bark-3.0-Clean-sherpa-onnx (rev `bdcbdca`): VET FIRST
  (user, 2026-10-21; replaces the earlier plain approval).
  1. Download only into a new, empty scratch dir. Never run `convert-bark.py`
     or any other script from that repo. Do not load its files yet.
  2. Read every non-weight file (scripts, configs, tokens, README). Report
     what each script does, its imports, and any network, file-system,
     subprocess, or eval/exec use.
  3. List each weight file with size and format. Confirm that sherpa-onnx
     would load only `.onnx` and tokens files, with no pickle or custom code.
  Vetting done. APPROVED (user, 2026-10-21): load only encoder.int8.onnx,
  decoder.int8.onnx, joiner.int8.onnx and tokens.txt from rev bdcbdca in
  sherpa-onnx and measure Clean on the same audio. Run no script from that repo.
  Remove all velddev files after the report. Record the revision and license in
  the report. Never commit these files; remove them after the report.

## Rules

- Research only. Do not edit `src/`, `pyproject.toml`, or any production
  file. No production commits. Your branch may carry only the report and
  evidence under `.hive/spec/stenographer-hub/tasks/26-bark-eval/evidence/` (committed with `git add -f`).
- Explicit downloads are authorised for this task only: the three model repos
  above. Download into a scratch dir inside your worktree (for example
  `.scratch/models/`), never into `~/.cache/huggingface` or the stenographer
  model dirs, and remove them after the report is verified (the manager tells you).
- New Python packages (transformers>=5.19, torch, constriction, etc.) go only in
  a separate scratch venv in your worktree, never in `.venv`. Create it with
  `.venv/bin/python -m venv .scratch/venv` (do not use bare `python3 -m venv`:
  system 3.12 lacks venv). Record installed size.
- Privacy: never commit, log or put in hive history any audio or transcript
  text from the user's recordings. The committed report holds numbers and
  public-corpus text only. Samples of output text from the user's audio go only
  in the final report you send to the manager (inbox), at most 3 short excerpts
  per model, and only once the audio source is confirmed.
- Do not open the microphone, run `live` or `run`, or change daemon or audio
  settings.
- Never signal a process or close a tab, pane or workspace that you did not
  start. Never work in workspace wBC.
- Do not push `dev` or `main`, open a pull request, or run a workflow.
- Conventional commits, no attribution trailers.
- Deliverable: `.hive/spec/stenographer-hub/tasks/26-bark-eval/evidence/report.md` (items 1-5, tables, exact
  commands and versions so a verifier can re-run one measurement), then
  `hive task complete`.
