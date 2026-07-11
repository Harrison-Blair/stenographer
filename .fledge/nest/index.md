---
generated: 2026-07-11T05:16:32Z
commit: f5694b5bffd265badb03101b726304b5e6a0efb4
agent: fledge-forager
fledge_version: 0.4.0
---

# Context Index

## architecture.md
Traces the end-to-end utterance flow (hotkey → record → transcribe → output), the `Session` orchestrator's role as the single lock-guarded state-transition point, the four injected component layers (hotkey/audio/asr/output), the live-streaming driver, cross-cutting concerns (config, capabilities, errors, notifications, update, bench), and the concurrency model (RLock + generation-counter pattern).
Read this when: understanding how a new mode or component would wire into `Session`, tracing a bug across threads, or planning any change that touches more than one layer.

## modules.md
Repo map — each top-level module (root package, `hotkey/`, `audio/`, `asr/`, `output/`, `tests/`, `scripts/`, `packaging/`, CI) with its purpose, key files, and a "Look here for" routing line.
Read this when: deciding which files/module a change belongs in, or getting oriented in an unfamiliar part of the tree.

## conventions.md
Reconciled coding/process conventions: SPDX headers, ruff config, error-handling policy (`StenographerError` + `notify_failure`/`fatal`/`degrade_capability`), the RLock + generation-counter concurrency pattern, config loading rules, logging format, release process (version bump gate), and test conventions.
Read this when: writing new code and needing to match existing style, error handling, logging, or concurrency idioms; before bumping the version for a release.

## data-model.md
Every dataclass/type in the codebase with fields and file references: `Config` and its nested sub-configs, `Capabilities`, ASR types (`SegmentInfo`, `WordInfo`, `TranscriptionResult`, `Job`), `Session`/`_LiveItem` state, hotkey `State`/`Action`/`Transition`/`HotkeyBinding`, `CueName`, `UpdateInfo`, benchmark types, error hierarchy.
Read this when: adding a new config field, a new data type, or needing exact field names/types for an existing type.

## dependencies.md
Every external dependency (Python packages, system CLIs invoked via subprocess, native libraries, services) with what it's used for and where.
Read this when: adding a new dependency, checking whether a capability is already probed, or working with subprocess-invoked tools (wtype, wl-copy, pw-play/paplay, notify-send, systemctl).

## entry-points.md
CLI subcommands and exit codes; the `Session` constructor boundary and every constructor-injected component's public method surface (the seams a new feature plugs into); config/capabilities/update entry points; systemd integration; build/install/release entry points.
Read this when: adding a CLI subcommand, wiring a new component into `Session`, or needing the exact public API of an existing component (Injector, ClipboardManager, HeuristicFormatter, Recorder, Worker, LazyModel, etc.).

## testing.md
pytest conventions: how to run (unit vs. full vs. single test), the `integration` marker, the 1:1 `tests/` ↔ `src/stenographer/` file mapping, per-area test file inventory, and recurring test patterns (MagicMock fixtures, `_make_x()`/`_fake_x()` naming, frozen-dataclass fixtures, caplog usage).
Read this when: writing tests for a new feature — find the existing pattern for the component type you're touching (pure state machine vs. subprocess wrapper vs. threaded orchestrator).

## domain.md
Glossary: recording trigger modes (PTT, toggle, double-tap, chord, cancel chord, generation), utterance lifecycle (segment, silence detection, batch vs. streaming, injection method), ASR concepts (compute type, beam size, lazy/eager, LocalAgreement-N, WER/RTF), output concepts (formatter, clipboard fallback), platform concepts (Wayland-only, input group, capability degradation), release/versioning terms.
Read this when: unsure what a domain term means in a spec, PR, or code comment; scoping a new feature that needs to reuse existing vocabulary correctly (e.g. distinguishing PTT from toggle from streaming).
