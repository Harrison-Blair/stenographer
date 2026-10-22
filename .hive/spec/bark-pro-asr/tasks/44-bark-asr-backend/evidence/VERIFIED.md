# Task 44 verification

Verdict: **pass**. Verifier: `t44-verifier-2`. Date: 2026-10-22.
Code reviewed: `0147bb1` on `task/44-bark-asr-backend`.
All commands ran from the task worktree root with its `.venv`.
No microphone, integration test, reinstall, or real user dictation was used.

## Verification items

| Item | Result | Observation |
| --- | --- | --- |
| 1. Bark recognizer and caller seam | pass | Reviewed `Model._load`: three int8 paths, tokens, `nemo_transducer`, CPU, greedy search, 16 kHz, configured threads or existing auto rule. Model tests and real load/decode pass. No `faster_whisper` import or old download caller remains in `src/`. |
| 2. Leading pad and shifted timestamps | pass | Independent red runs detect missing pad, missing shift, and missing clamp. Restored code passes. Real first-word span is 0.07–0.39 s. |
| 3. Results and token mapping | pass | One segment per decode; SentencePiece joining; duration spans; probability from mean log-prob or 1.0; no confidence gate; `_validate_output` retained. Independent joining, probability, and empty-text mutations fail tests. `SegmentInfo` has no no-speech field. |
| 4. Dictation VAD | pass | Real `PhraseSegmenter` supplies the existing Silero parameters. Each kept region has up to 0.25 s pre-pad. Daemon wires the filter before worker decode. Tests detect removed pre-pad, removed flush, decoding no-speech, and ignoring VAD output. Real silence and public speech pass. |
| 5. Live and Files | pass | Restoring the old live gate fails live tests; restored code passes. Whitespace is dropped. Both `LiveSession` and `FilesEngine` retain `phrase.start/end` and use phrase duration for speaker assignment. Full gate covers both. |
| 6. Probes and hub download | pass | Handler, capabilities, and wizard use Bark cache probe. Hub default download uses Bark plus the Silero live model entry. Restoring the four original probe/hub files gives 15 failures; restoring task code gives 30 passes. |
| 7. Regression tests | pass | Red and green reruns below confirm observable assertions. Only recognizer, VAD, and delivery seams substitute external services. Source restored after every red run; `git diff --exit-code` was clean. |
| 8. Real install, public clip, silence, cleanup | pass | Reproduced after manager relayed user permission on 2026-10-22. Results below. Scratch model and build data removed. User data directory contains only `_internal` and `stenographer`. |
| Worktree gate | pass | Repeat gate has zero failures. Initial hub lifecycle timing failure is recorded below. |
| Design | pass | No layout change. The brief exempts text-only changes from boards. No screen or colour-state change requires a capture. |

The removal of Whisper config/dependency/bench/study code belongs to task C,
except the transcription bench deletion approved by the manager in V9.
`scripts/live_bench.py` still imports `faster_whisper`; the spec explicitly
assigns its deletion to task C. The production module import check above is
limited to `src/`. Documentation changes belong to task D under this spec.

## Independent red and green runs

Each mutation ran alone. The original bytes were restored in a `finally` block.
Commands were `.venv/bin/pytest -q TEST_FILE -m "not integration"`.

| Deliberate break | Test file | Red result |
| --- | --- | --- |
| Remove leading pad | `tests/lib/transcribe/test_model.py` | 2 failed, 34 passed |
| Set timestamp offset to zero | same | 4 failed, 32 passed |
| Remove timestamp clamp | same | 1 failed, 35 passed |
| Start a new word for every token | same | 4 failed, 32 passed |
| Force probability to 1.0 | same | 1 failed, 35 passed |
| Keep empty decode segment | same | 2 failed, 34 passed |
| Remove VAD pre-pad | `tests/lib/transcribe/test_dictation_vad.py` | 4 failed, 3 passed |
| Drop flushed VAD region | same | 1 failed, 6 passed |
| Decode when no speech remains | `tests/lib/daemon/test_pipeline.py` | 1 failed, 18 passed |
| Send original audio instead of VAD speech | same | 1 failed, 18 passed |
| Restore removed live no-speech gate | `tests/lib/live/test_live_session.py` | 11 failed, 10 passed; removed field raises AttributeError |
| Remove XDG_DATA_HOME isolation | `tests/test_host_directory_guard.py` | 1 failed |

Green after all restores:

```sh
.venv/bin/pytest -q tests/lib/transcribe/test_model.py tests/lib/transcribe/test_dictation_vad.py tests/lib/daemon/test_pipeline.py tests/lib/live/test_live_session.py tests/test_host_directory_guard.py tests/cli/transcribe/test_handler.py tests/lib/diagnostics/test_capabilities.py tests/cli/hub/test_setup_doctor.py -m "not integration"
# 114 passed in 10.02s
```

Probe red run temporarily restored handler, capabilities, wizard and hub app
from `a115eea`, then ran their handler/capabilities/setup-doctor tests:
15 failed, 15 passed in 6.64 s. After restoration, the same command gave
30 passed in 6.37 s.

## Real reproduction

Scratch root: `$PWD/.hive/tmp/verifier44/`.

```sh
XDG_DATA_HOME="$PWD/.hive/tmp/verifier44/data" /usr/bin/time -v .venv/bin/stenographer model download --asr
```

Exit 0. Created a system-Python temporary venv, installed pinned converter
packages, fetched pinned Pro, converted and checked the output, installed
Bark, and downloaded Silero VAD. Output named Conway Research, CC BY 4.0,
and local int8 ONNX conversion. Elapsed 1:26.55. Peak RSS 10,736,768 KiB.
The ASR directory contained only `bark-pro-int8/` and its seven contract files.
No `.build-*` directory remained.

The first evidence-script attempt used a nonexistent reference path under
`clips/` and failed before model load or decode. The corrected command was:

```sh
XDG_DATA_HOME="$PWD/.hive/tmp/verifier44/data" .venv/bin/python .hive/spec/bark-pro-asr/tasks/44-bark-asr-backend/evidence/bark_evidence.py /home/penguin/source/stenographer/.cache/transcription-study-20260912/clips/libri-clean-1580-141084-0041.wav /home/penguin/source/stenographer/.cache/transcription-study-20260912/references/libri-clean-1580-141084-0041.txt "$PWD"
```

Clip and reference were read in place. No copy was made. Script review confirms
it invokes real `Model.transcribe`, real `dictation_speech` and real
`UtterancePipeline`; counting worker and recording deliverer avoid native IPC
and delivery. The clip has 7.99 s of 16 kHz public LibriSpeech audio.

| Measurement | Result |
| --- | --- |
| Model load, 8 auto threads | 1.92 s; RSS after load 1,167 MiB |
| Direct decode | 0.56 s; RTF 0.070; 1 segment, 30 words; WER 0.000 |
| RSS after direct decode | 1,220 MiB; peak 1,220 MiB |
| Dictation | DELIVERED; 1 decode; VAD kept 7.92 s |
| Dictation decode and whole pipeline | 0.53 s and 0.62 s |
| RSS after dictation | 1,229 MiB; peak 1,231 MiB |
| 2 s digital silence, real VAD | 0 kept frames |
| Silence, stock RMS gate | SILENT; 0 decode calls; no delivery |
| Silence, RMS gate disabled | SILENT; 0 decode calls; no delivery |

Both speech paths produced this public-clip text (WER 0.000):

> No harm would have been done had it not been that as he passed your door, he perceived the key which had been left by the carelessness of your servant.

First word: 0.07–0.39 s, p=1.000. Last word: 7.19–7.75 s, p=0.999.

Cleanup: removed `.hive/tmp/verifier44/data` and confirmed it was absent.
The converter already removed its temporary venv, BF16 source and downloads.
No scratch clip existed. `ls -A ~/.local/share/stenographer` showed exactly
`_internal` and `stenographer`. Temporary verification scripts and output files
were removed after this report was written.

## Gate and timing flake

Initial exact gate test command:

```sh
.venv/bin/pytest -m "not integration"
# 1 failed, 2779 passed, 1 skipped, 7 deselected in 111.66s
```

Failure:
`tests/cli/hub/test_app.py::test_pilot_lifecycle_worker_finishes_after_hub_screen_unmount_without_failure`.
The timer entered `app.py:725` `_refresh_live_view`, then `app.py:498`
`_refresh_view`, after the hub screen was removed.
`query_one("#sidebar", Static)` raised `NoMatches` on the default screen;
the waiting start-recording worker was cancelled. This path is unchanged by
the task diff. The task only changes the hub's default model download and
models-step model identifier. No causal regression link was found.

One immediate isolated rerun passed. At the manager's request, five further
isolated runs passed (0.49, 0.49, 0.48, 0.54, 0.48 s). The manager also reported
clean-export baseline and task runs with no failure; those runs were not made
by this verifier. The initial failure is classified as a timing flake.
The brief's known `test_sessions.py` timing test passed in both full runs.

The complete gate was then repeated, with no source change:

```sh
.venv/bin/ruff check .
# All checks passed! (exit 0)
.venv/bin/ruff format --check .
# 813 files already formatted (exit 0)
.venv/bin/pytest -m "not integration"
# 2780 passed, 1 skipped, 7 deselected in 113.06s (exit 0)
.venv/bin/stenographer --help
# Expected command usage and command list (exit 0)
```

The skip is the speaker tracker test whose optional public clips are absent.
Seven integration tests were deselected. This Python task uses the four-command
repository gate; the hive Go gate does not apply.
