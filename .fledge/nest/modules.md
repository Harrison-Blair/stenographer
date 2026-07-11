---
generated: 2026-07-11T05:16:32Z
commit: f5694b5bffd265badb03101b726304b5e6a0efb4
agent: fledge-forager
fledge_version: 0.4.0
---

# Modules

Repo map: each module, its purpose, key files, and where to look for what.

## `src/stenographer/` (root package)
Purpose: package root — CLI entry point, config, cross-cutting policy (errors, capabilities, notifications, self-update, benchmarking).
Key files: `cli.py` (`main()`, all `cmd_*` handlers, `_build_session()`), `_parser.py` (argcomplete-light argument parser), `config.py` (`Config` schema/loading), `capabilities.py` (`Capabilities.probe()`), `errors.py` (exception hierarchy + policy fns), `notification.py` (`DesktopNotification`), `update.py` (self-update), `bench.py` (ASR benchmarking harness), `__init__.py` (`__version__` from importlib.metadata), `session.py` (`Session` orchestrator), `live.py` (`LiveStreamer`).
Look here for: CLI subcommand wiring, config schema/defaults, error-handling policy, capability probing, desktop notifications, self-update flow, the per-utterance state machine (`session.py`), and the live-streaming driver (`live.py`).

## `src/stenographer/hotkey/`
Purpose: global hotkey binding parsing, pure trigger state machine, and the evdev listener thread(s).
Key files: `binding.py` (`HotkeyBinding.parse/to_evdev_codes/matches`), `state_machine.py` (`HotkeyStateMachine`, `State`, `Action`, `Transition`), `listener.py` (`HotkeyListener`, `auto_detect_path(s)`, multi-HID reader threads).
Look here for: adding/changing a keybind, changing PTT-vs-toggle timing rules, evdev device auto-detection, chord parsing/validation.

## `src/stenographer/audio/`
Purpose: microphone capture (with silence detection and resampling) and audio-cue feedback playback.
Key files: `capture.py` (`Recorder`, `_resample_poly`), `feedback.py` (`Feedback`, `CueName` — 11 named cues).
Look here for: recording lifecycle, silence-detection thresholds, sample-rate/channel negotiation, adding a new audio cue, cue playback (pw-play/paplay), volume/mute handling.

## `src/stenographer/asr/`
Purpose: offline speech-to-text via faster-whisper — batch transcription, word-timestamped transcription, off-thread execution with cancellation, and the live word-commit policy.
Key files: `model.py` (`Model`, `LazyModel`, `SegmentInfo`, `WordInfo`, `TranscriptionResult`), `worker.py` (`Worker`, `Job`, `CancelledError`), `streaming.py` (`StreamingTranscriber`, LocalAgreement-N).
Look here for: ASR model loading/unloading, submitting transcription jobs, cancellation semantics, the live streaming commit algorithm (word agreement, rebase/trim).

## `src/stenographer/output/`
Purpose: turning final/committed transcript text into typed keystrokes and clipboard content, with heuristic text formatting in between.
Key files: `inject.py` (`Injector` — `type_text()`, `paste()`, both via `wtype` subprocess), `clipboard.py` (`ClipboardManager` — `copy()`/`read()` via `wl-copy`/`wl-paste`), `formatter.py` (`HeuristicFormatter` — `feed()` incremental, `format_batch()` one-shot; spacing/capitalization/paragraph-pause rules).
Look here for: how transcript text is typed at the cursor, clipboard fallback behavior, spacing/capitalization/paragraph-break rules, adding a new output sink or formatting rule.

## `tests/`
Purpose: pytest suite mirroring `src/stenographer/` one-to-one (e.g. `test_capture.py` ↔ `audio/capture.py`), plus `fixtures/` for shared test data.
Key files: one `test_<module>.py` per source module (`test_session.py`, `test_hotkey.py`, `test_lazy_model.py`, `test_worker_cancel.py`, `test_streaming.py`, `test_capture.py`, `test_feedback.py`, `test_inject.py`, `test_clipboard.py`, `test_formatter.py`, `test_config.py`, `test_capabilities.py`, `test_errors.py`, `test_notification.py`, `test_update.py`, `test_bench.py`, `test_transcription.py`, `test_cli_completion.py`, `test_cli_systemd.py`, `test_cli_update.py`, `test_live.py`).
Look here for: existing test conventions/fixtures for a module before writing a new test file; the `integration` marker pattern for tests touching real audio/clipboard/display.

## `scripts/`
Purpose: developer/build utility scripts — not shipped in the package.
Key files: `build.sh` (PyInstaller build), `install.sh` (source install + systemd), `build-and-install.sh` (wrapper), `download_model.py` (HF `snapshot_download`), `gen_cues.py` (synthesizes the 11 WAV cues into `assets/sounds/`), `install-hooks.sh` (git hooks config).
Look here for: how the standalone binary is built/installed, how ASR models are fetched, how audio cues are generated (useful if a feature needs a new cue).

## `packaging/`
Purpose: PyInstaller packaging config and end-user distribution assets.
Key files: `stenographer.spec` (PyInstaller entry point/hidden imports/data files), `hook-sounddevice.py` + `rthooks/py_rth_portaudio.py` (exclude/relink system audio libs), `install.sh` (curl-pipeable installer for prebuilt releases), `stenographer.service.in` (systemd user unit template), `stenographer-completion.bash` (shell completion).
Look here for: what ships in the frozen binary, systemd unit contents, the end-user (non-source) install flow.

## `.github/` + `.githooks/` (misc/CI)
Purpose: git hooks and CI/CD — pre-commit formatting, release pipeline, badge updates.
Key files: `.githooks/pre-commit` (ruff format on staged files), `.github/workflows/release.yml` (lint → test → build → publish GitHub Release on push to `main`), `.github/workflows/release-badge.yml` (updates orphan `badges` branch).
Look here for: what CI enforces before a merge to `main` is releasable (version bump requirement, lint/test gates).

## Root files
Purpose: project metadata and docs.
Key files: `pyproject.toml` (hatchling; single source of truth for metadata/deps/version; ruff/pytest config), `CLAUDE.md`/`AGENTS.md` (agent-facing dev guidance), `README.md` (user-facing install/config/usage), `BUILD.md` (binary build instructions + runtime deps table), `LICENSE` (GPL-3.0).
Look here for: dependency versions, version bump location (`[project].version`), documented runtime requirements.
