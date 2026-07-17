---
generated: 2026-07-17T01:39:59Z
commit: 939420f205b102d61ab3d7ed257a1680a61483dc
agent: fledge-forager
fledge_version: 0.5.8
---

# Context Index

## architecture.md
Traces the full hotkey→record→ASR→output pipeline and the three processing pipelines inside `Session` (batch / paste-chunk-aggregation / streaming), plus the cross-module invariants (typed text never revised, clipboard as independent fallback, capability degradation, single-lock state transitions). Ends with a section mapping the three planned changes (text streaming, PTT trigger mode, paste-based injection) onto the exact modules and existing hooks they'll touch.
Read this when: you need the big picture before touching `session.py`, `live.py`, or any component boundary, or before scoping any of the three planned features.

## modules.md
Repo map covering all 11 scouted modules/subpackages (root, github, packaging, scripts, src cross-cutting, session+live, hotkey, audio, asr, output, tests) — purpose, key files, and a "Look here for" pointer per module.
Read this when: you know *what* you need to change but not *which file* — start here to locate the right module before diving into a specific doc.

## conventions.md
Reconciled coding conventions: SPDX/ruff/src-layout style, the `StenographerError`/exit-78/`notify_failure` error-handling contract, the recurring generation-counter and single-RLock concurrency patterns, frozen-dataclass config conventions, path/asset resolution for PyInstaller vs. wheel installs, and CI/release conventions.
Read this when: writing new code and you want it to match existing idioms, especially error handling, threading/locking, or config schema additions.

## data-model.md
Every dataclass/type/schema in the codebase by defining file: the full `Config` hierarchy, `Capabilities`, ASR types (`SegmentInfo`, `WordInfo`, `TranscriptionResult`, `Job`), `Session`/`LiveStreamer` internal state, hotkey FSM states/actions/`Transition`, audio buffer types, output `_Token` protocol, `UpdateInfo`, bench types.
Read this when: you need to know a type's exact fields/shape before writing code that constructs, consumes, or extends it — especially `Config` sub-dataclasses or `Session`/`LiveStreamer` internal state.

## dependencies.md
All external dependencies deduplicated with usage notes: Python runtime/dev/build deps from `pyproject.toml`, required system tools (wtype, wl-copy/wl-paste, pw-play/paplay, systemd, libevdev, libportaudio2), GitHub Actions, and the separately-fetched ASR model.
Read this when: adding a new dependency (check it's not already present under a different name), or diagnosing a missing-capability/`doctor` failure.

## entry-points.md
All 13 CLI subcommands (`run`, `dictate`, `transcribe`, `bench`, `model download`, `update`, `doctor`, `devices`, systemd verbs), the `Session`/`LiveStreamer` programmatic entry points, key component public APIs, and the authoritative dev/build/test/release commands.
Read this when: wiring a new subcommand, calling into `Session`/`LiveStreamer` from new code, or you need the exact command to lint/test/build/install.

## testing.md
Framework and execution details (pytest, `-m "not integration"`, the exact 4 `@pytest.mark.integration` tests and their gating), a per-file coverage table for all 26 test files (what's covered, notable patterns like the `test_prefix_invariant_M6` live-typing check), and shared test-helper conventions.
Read this when: writing or modifying tests, or checking whether a behavior is already covered before assuming it needs a new test — check the Open Questions first for two files (`test_session.py`, `test_live.py`) whose full coverage wasn't exhaustively catalogued.

## domain.md
Glossary of dictation-daemon vocabulary: hotkey/trigger-mode terms (chord, PTT, toggle, hybrid, double-tap window), recording/audio terms (silence detection, flush, resampling), ASR/streaming terms (LocalAgreement-N, committed prefix, re-decode, trim/rebase, tail-silence guard, RTF, WER), and output/formatting terms (injection, paste mode, append-only, capability degradation).
Read this when: you hit an unfamiliar term in code, tests, or a planning doc and need the precise in-repo definition — especially before working on the streaming, hotkey-trigger-mode, or paste-injection changes, since those areas have the densest domain vocabulary.

## Open Questions (cross-cutting, not owned by one doc)
- Live-streaming RTF on real (non-benchmark) CPU hardware is unmeasured (architecture.md, domain.md).
- Whether a third "ptt-only" `trigger_mode` value is planned, or "hybrid" remains the sole PTT-capable mode (architecture.md, domain.md).
- Whether `silence_rms_threshold` default (0.01) should be lowered for quiet mic input (domain.md; corroborates existing project memory).
