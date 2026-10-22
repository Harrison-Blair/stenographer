# Task: bark-asr-backend — decode with Bark Pro in dictation, live and Files

| Item | Value |
| --- | --- |
| Tier | strong |
| Feature | bark-pro-asr |
| Depends on | 32-pro-convert-download (landed, dev a115eea) |

## Overview

The design authority is `.hive/spec/bark-pro-asr/README.md` on dev. Read it in full.
This task is spec task B. Follow the Contracts section "Backend" exactly. Task 32
added `lib/transcribe/bark_download.py` (model dir, no-arg `is_model_cached()`)
and `bark_pins.py`; build on them. Task C (after this) removes faster-whisper from
pyproject and packaging, huggingface_hub, the Whisper config keys, the bench and
study scripts, and `lib/transcribe/download.py`. Do not do task C work.

## Requirements

1. Replace `lib/transcribe/model.py`'s faster-whisper backend with
   `sherpa_onnx.OfflineRecognizer.from_transducer(..., model_type="nemo_transducer")`
   on the three int8 files and `tokens.txt` in the Bark model dir: greedy search,
   provider CPU, `num_threads` from `cpu_threads` (0 = the existing auto rule).
   `Model(cfg)`, `Model.transcribe(samples)` and `Model.close()` stay the seam. No
   module may import faster_whisper after this task (pyproject keeps the
   dependency until task C).
2. 0.25 s leading-silence pad before the decode; timestamps shifted back and clamped
   at 0.
3. Remove `SegmentInfo.no_speech_prob`. `_assemble` loses `silence_threshold`.
   `_validate_output` stays. One `SegmentInfo` per decode; words from sherpa token
   timestamps and durations, joined at the SentencePiece word marker;
   `WordInfo.probability` per the spec (information only).
4. Dictation silence: run sherpa Silero VAD (the same model file and parameters as
   `PhraseSegmenter`) over the capture first, with 0.25 s pre-pad per speech region.
   No speech: no decode, empty result. `vad_seconds` reports the speech kept. Empty
   or whitespace results are dropped as today.
5. Live: remove the `no_speech_prob >= 0.6` gate in `live_session.py`; drop a phrase
   only when its text is empty. Live and Files keep their VAD phrase times.
6. Switch the model-presence probes to the Bark `is_model_cached()`:
   `cli/transcribe/handler.py`, `lib/diagnostics/capabilities.py`,
   `cli/hub/setup_wizard.py`, and the hub download in `cli/hub/app.py` (it calls the
   Whisper `download_model`; route it to the task 32 download). After this task the
   only remaining user of `lib/transcribe/download.py` may be its own tests.
   The Whisper config keys stay readable but unused until task C.
7. Tests: failing-first unit tests for the pure logic (pad and timestamp shift,
   token-to-word joining, probability mapping, empty-text drops, dictation VAD
   no-speech path, the live gate removal). Inject the recognizer and the VAD through
   seams; do not mock OS calls. Update the existing model and decode tests that
   use faster-whisper.
8. Real evidence (no microphone):
   - Install the model with the real `stenographer model download --asr` into a
     scratch `XDG_DATA_HOME` in your worktree. Never the user's real data dir.
     WAIT for the manager's go-ahead before this download; the user authorises it
     separately. Write all the code and tests first.
   - Decode one public test clip through `Model.transcribe`, then through the
     dictation path (VAD then decode). The manager names the clip source with the
     go-ahead. Record the decoded text of the public clip only, the decode time, and
     the RSS. Then decode 2 s of digital silence and show an empty result with no
     decode call.
   - Delete the scratch model, downloads and clip after recording.

Evidence folder: `.hive/spec/bark-pro-asr/tasks/44-bark-asr-backend/evidence/`.

## Design

No UI layout change. The hub only changes which probe and download it calls. No
board is needed (spec decision 12, text-only changes).

## Rules

- Follow the repository AGENTS.md. Linux only. Keep the headless core.
- Your worktree has no `.venv`. Agents never create the repo venv: ask the manager
  to have the user run `! python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'`
  in your pane, and wait for the gate. Write code meanwhile.
- Never run sudo. Never run any git stash command (stash@{0} is the user's WIP).
- Do not open the microphone, run `live` or `run`, or run integration tests. Only
  the downloads in requirement 8, after the go-ahead.
- No transcript text or audio in logs, history or analytics. The evidence may hold
  the decoded text of the public clip only.
- Never signal a process or close a pane you did not start. Never work in wBC.
- Do not push dev or main, open a PR, or run a workflow. Conventional commits, no
  attribution trailers. Evidence committed with `git add -f`.
- Gate before `hive task complete`, zero failures, in the worktree `.venv`:
  `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`,
  `.venv/bin/pytest -m "not integration"`, `.venv/bin/stenographer --help`.
  If tests/cli/hub/test_sessions.py::test_session_playback_toggles_and_jobs_run_without_blocking_navigation
  fails, rerun it alone 5 times and record that; it is a known timing flake.
