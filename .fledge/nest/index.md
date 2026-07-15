---
generated: 2026-07-15T17:38:33Z
commit: d621b46261d9509fccbdffc4686be0b876c7951e
agent: fledge-forager
fledge_version: 0.5.4
---

# Context Index

Generated: 2026-07-15T17:38:04Z
Commit: d621b46261d9509fccbdffc4686be0b876c7951e

## architecture.md
Describes how the pipeline fits together: `Session` as the lock-guarded orchestrator, the hotkey→record→ASR→output component chain, the live-streaming invariant (typed text is never revised), and cross-cutting policies (config, capabilities, errors, notifications, update, single-instance lock). Also covers the packaging/distribution architecture (frozen binary vs. system libraries).
Read this when: you need to understand how components wire together, are tracing a callback/state-transition path across module boundaries, or are deciding where a new cross-cutting concern belongs.

## modules.md
A per-directory map (root, .github, packaging, scripts, src/stenographer core, hotkey, audio, output, asr, tests) — purpose, key files, and "Look here for" pointers for each.
Read this when: you know roughly what you're looking for but not which file/directory owns it, or you're getting oriented in the repo for the first time.

## conventions.md
Reconciled coding/tooling/process conventions: Python style (dataclasses, naming, pure-vs-stateful split), ruff/pytest config, build conventions (hatchling, PyInstaller, bash script conventions), error-handling policy, threading patterns, and the release process (dev→main version bump gate).
Read this when: writing new code and need to match existing style, adding a new component and unsure how it should handle errors/threading, or preparing a release/PR.

## data-model.md
Every dataclass/Protocol/Literal type in the pipeline: the 9-part `Config` hierarchy, ASR types (`SegmentInfo`, `WordInfo`, `TranscriptionResult`, `Job`), session/live-streaming state, `Capabilities`, `UpdateInfo`, hotkey `State`/`Action`/`Transition`, `CueName`, and benchmarking types.
Read this when: you need exact field names/types for a dataclass, are wiring new config, or need to know what shape of data flows between two components.

## dependencies.md
Deduplicated external dependency list with usage notes: Python runtime/dev/build deps, required system CLIs and libraries (wtype, wl-copy, libportaudio, libevdev), external services (GitHub Releases, Hugging Face Hub, optional local LLM endpoint), and CI-specific dependencies.
Read this when: adding/removing a dependency, debugging a missing-tool/capability failure, or checking what a fresh install/CI environment needs.

## entry-points.md
Every way into the system: the `stenographer` CLI and its subcommands (run, dictate, transcribe, model download, bench, update, doctor, devices, enable/disable/start/stop), each component's public class/method API, and the build/install/test/release commands.
Read this when: you need to invoke or extend a subcommand, call a component's public API, or need the exact command to build/install/lint/test the project.

## testing.md
How the ~7,400-line pytest suite is organized: running unit vs. integration tests, marker/skip conventions, mocking patterns (fakes vs. monkeypatch vs. pure-function tests), and a file-by-file coverage map of all 24 test files.
Read this when: writing a new test and need to match existing patterns, deciding whether a test should be `integration`-marked, or figuring out which existing test file already covers a given behavior.

## domain.md
Glossary of dictation-domain and project-specific terms: hotkey/recording modes (PTT, toggle, chord, cancel, discard, prompt mode), transcription/streaming terms (LocalAgreement-N, committed, RTF, WER, tail-silence guard), audio/output terms (RMS threshold, cue, injection, clipboard fallback), and packaging/release terms (frozen binary, onedir, SHA-256 verification).
Read this when: you encounter an unfamiliar term in code, comments, or a spec/plumage, and need its precise meaning in this codebase.
