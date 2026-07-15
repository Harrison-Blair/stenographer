---
generated: 2026-07-15T17:38:33Z
commit: d621b46261d9509fccbdffc4686be0b876c7951e
agent: fledge-forager
fledge_version: 0.5.4
---

# Modules

A per-directory map of the repository: what each module is for, its key files, and where to look for specific behavior.

## root

Project metadata and top-level docs: `pyproject.toml` (hatchling, version, deps, ruff/pytest config), `README.md`, `BUILD.md`, `AGENTS.md`/`CLAUDE.md` (dev guidance), `LICENSE` (GPL-3.0-or-later), `.python-version` (3.14).
Look here for: release/version source of truth, top-level dependency list, license/SPDX policy.

## .github

Automation: pre-commit hook, CI, and release pipelines.
Key files: `.githooks/pre-commit` (ruff format on staged Python), `.github/workflows/ci.yml` (lint/test/build on PR), `.github/workflows/release.yml` (version extraction, build, GitHub Release publish on push to main), `.github/workflows/release-badge.yml` (shields.io badge on `badges` orphan branch).
Look here for: what CI actually gates, how releases get versioned/published, why a merge to main might be rejected (duplicate version tag).

## packaging

PyInstaller bundling and end-user install script.
Key files: `stenographer.spec` (Analysis/EXE/COLLECT config, `collect_submodules("stenographer")`), `hook-sounddevice.py` (excludes system audio libs from bundle), `rthooks/py_rth_portaudio.py` (sets `LD_LIBRARY_PATH` at runtime), `install.sh` (curl-able installer: deps check, download+SHA-256 verify, systemd setup), `stenographer.service.in` (systemd user unit template), `stenographer-completion.bash` (argcomplete bash/zsh completion).
Look here for: what's bundled vs. expected on the system at runtime, how the frozen binary resolves native libraries, the end-user install flow.

## scripts

Build/install/asset-generation tooling invoked by developers and by `install.sh`.
Key files: `build.sh` (wraps `pyinstaller` on `packaging/stenographer.spec`), `build-and-install.sh` (build.sh + install.sh wrapper), `install.sh` (6-step local deploy: build if missing, copy to `~/.local/share/stenographer/`, symlink, install completion, systemd unit, enable+start), `install-hooks.sh` (`git config core.hooksPath .githooks`), `download_model.py` (fetches ASR model via `huggingface_hub.snapshot_download`), `gen_cues.py` (generates the 13/16 WAV feedback cues into `assets/sounds/`).
Look here for: how the standalone binary gets built and installed locally, how audio cues are (re)generated, how the ASR model is fetched.

## src/stenographer (core: cli, config, session, cross-cutting)

Top-level dispatch, config schema, and the per-utterance orchestrator; everything not owned by a component submodule.
Key files: `cli.py` (`main`, subcommand dispatch), `_parser.py` (lightweight argparse for argcomplete), `config.py` (`Config` dataclass hierarchy + TOML load/validate), `session.py` (`Session` orchestrator), `live.py` (`LiveStreamer`), `errors.py` (`StenographerError` hierarchy + policy functions), `capabilities.py` (`Capabilities.probe()`), `notification.py` (`DesktopNotification`), `update.py` (self-update), `llm.py` (`rewrite_prompt`, prompt-mode LLM rewrite), `bench.py` (ASR benchmarking: WER, RTF).
Look here for: subcommand behavior, config schema/validation rules, session/cancel/discard semantics, error-handling policy, self-update mechanics.

## src/stenographer/hotkey

Hotkey binding parsing, evdev listener, and the pure PTT/toggle state machine.
Key files: `binding.py` (`HotkeyBinding.parse`), `listener.py` (`HotkeyListener`, multi-device evdev reader threads), `state_machine.py` (`HotkeyStateMachine`: IDLE/RECORDING_PTT/PENDING_TAP/TOGGLE_LATCHED/TOGGLE_STOPPING).
Look here for: how the hybrid PTT/toggle trigger works, double-tap timing, cancel-chord handling, multi-HID keyboard quirks.

## src/stenographer/audio

Microphone capture and audio feedback cues.
Key files: `capture.py` (`Recorder`: PortAudio stream, RMS silence detection, polyphase FIR resample fallback), `feedback.py` (`Feedback`: `pw-play`/`paplay` cue playback).
Look here for: silence-detection thresholds, sample-rate/channel fallback behavior, cue playback.

## src/stenographer/output

Text injection and clipboard.
Key files: `inject.py` (`Injector`: `wtype` text injection, paste-via-Ctrl+V fallback), `clipboard.py` (`ClipboardManager`: `wl-copy`/`wl-paste`), `formatter.py` (`HeuristicFormatter`: append-only spacing/capitalisation/paragraph-break formatting).
Look here for: how text reaches the screen/clipboard, truncation limits, formatting heuristics.

## src/stenographer/asr

faster-whisper wrapper, background worker, and the streaming word committer.
Key files: `model.py` (`Model`, `LazyModel`, `SegmentInfo`/`WordInfo`/`TranscriptionResult`), `worker.py` (`Worker`: job queue, cancellation, idle-unload plumbing), `streaming.py` (`StreamingTranscriber`: pure LocalAgreement-N committer).
Look here for: batch vs. word-timestamped transcription, model lazy-load/idle-unload, the streaming commit algorithm.

## tests

~7,400-line pytest suite mirroring `src/stenographer/`, 24 files.
Key files: `test_session.py` (1,460 lines — the core orchestrator), `test_config.py` (885 lines), `test_update.py` (593 lines), `test_hotkey.py` (581 lines), `test_capture.py` (558 lines), `test_live.py` (524 lines).
Look here for: expected behavior/edge cases of any component; `integration`-marked tests show what touches real hardware/tools.

## Open Questions

- How does `scripts/install.sh`'s `stenographer.service.in` → `stenographer.service` templating step relate to the one embedded directly in `scripts/install.sh` (unit content built inline)? Two systemd-unit generation paths are referenced across `packaging.md` and `scripts.md` — unclear if they're kept in sync or one is stale.
