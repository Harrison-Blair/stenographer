---
generated: 2026-07-15T17:38:33Z
commit: d621b46261d9509fccbdffc4686be0b876c7951e
agent: fledge-forager
fledge_version: 0.5.4
---

# Conventions

Coding, tooling, and process conventions observed across the repository, reconciled where scout reports overlapped or disagreed.

## Licensing & headers

- Every source file (Python, bash, YAML workflows) carries `# SPDX-License-Identifier: GPL-3.0-or-later` at the top (`root.md`, `.github.md`, `packaging.md`, `scripts.md`, `src-asr.md`, `src-audio.md`, `src-core.md`, `src-hotkey.md`, `tests.md`).
- Project license: GNU GPL v3-or-later (`LICENSE`).

## Python style

- `from __future__ import annotations` used for forward references (`src-audio.md`).
- Comprehensive type hints throughout; `TYPE_CHECKING`-gated imports to avoid runtime import cycles (`src-asr.md`, `src-core.md`).
- Dataclasses used heavily; data-carrying types (`SegmentInfo`, `WordInfo`, `TranscriptionResult`, `Capabilities`, `UpdateInfo`) are `frozen=True` (immutable) (`src-asr.md`, `src-core.md`).
- Naming: public classes in `TitleCase` (`Recorder`, `Injector`, `HotkeyListener`); private methods/attributes/constants prefixed `_` (`_on_audio`, `_FALLBACK_SAMPLE_RATES`); callbacks named `on_*` (`on_segment`, `on_loaded`) (`src-audio.md`, `src-hotkey.md`, `src-core.md`).
- Keyword-only arguments after `*` in constructors and public methods, e.g. `Recorder.__init__(self, *, sample_rate=..., device=...)` (`src-audio.md`).
- Module-level loggers via `log = logging.getLogger(__name__)`; debug-level logging for expected/no-op paths (e.g. tool unavailable), error-level for real failures; full transcript text is logged only at DEBUG (privacy) (`src-audio.md`, `src-core.md`).
- Sentinel objects used to distinguish special queue/state values from real data (`_UNLOAD` in `asr/worker.py`, `_PARTIAL`/`_FINAL`/`_ABORT` in `live.py`) (`src-asr.md`, `src-core.md`).
- Pure vs. stateful separation is deliberate: `HotkeyStateMachine` and `StreamingTranscriber` are pure (no I/O/timers/side effects) so they're easy to unit-test; I/O-touching components (`Recorder`, `Injector`, `ClipboardManager`) wrap subprocess/hardware calls and expose `close()` for uniform cleanup (`src-hotkey.md`, `src-asr.md`, `src-audio.md`).

## Linting & formatting

- `ruff` — `line-length = 100`, `target-version = "py314"`, rules `E,F,I,B,UP,N,SIM,RUF` (`root.md`, `src-core.md`).
- `.githooks/pre-commit` runs `ruff format` on staged `*.py` files and re-stages them; prefers `.venv/bin/ruff`, falls back to system `ruff` (`.github.md`). Enabled via `scripts/install-hooks.sh` (`git config core.hooksPath .githooks`).
- CI (`ci.yml`) checks lint and `ruff format --check` before test/build.

## Build & packaging conventions

- `hatchling` via `pyproject.toml` is the single source of truth for metadata/deps — no `setup.py`/`setup.cfg` (`root.md`).
- src-layout package (`src/stenographer/`); tests mirror it 1:1 (`tests/test_*.py`) (`root.md`).
- PyInstaller spec (`packaging/stenographer.spec`) documents in comments which system libraries are intentionally excluded from the bundle (`packaging.md`).
- All `.sh` scripts open with `#!/usr/bin/env bash` and `set -euo pipefail` (`scripts.md`, `packaging.md`).
- Bash conventions: helper functions (`info`, `warn`, `err`, `ok`) for consistent colored messaging; `ask_yn`/`ask_default` with `/dev/tty` fallback for prompts when piped through `curl`; section delimiters (`# ── label ──`) (`packaging.md`, `scripts.md`).
- Python CLI scripts use `argparse.ArgumentParser` and `if __name__ == "__main__": sys.exit(main())` (`scripts.md`).

## Error handling policy

- All components raise `StenographerError` subclasses (`ConfigError`, `CapabilityError`, `AudioCaptureError`, `TranscriptionError`, `UpdateError`, `LlmError`) rather than inventing ad hoc behavior; policy funneled through `notify_failure`, `fatal`, `degrade_capability` (`errors.py`, per `root.md`, `src-core.md`).
- Missing required capability (hotkey device, mic, ASR model) → exit code 78 (`EX_CONFIG`) (`root.md`).
- Bad config value → `ConfigError` with dotted key path and reason, exit 78 (`src-core.md`).
- Fire-and-forget cleanup (e.g. cue playback on shutdown) wrapped in `contextlib.suppress` (`src-core.md`).
- I/O components (`audio/`, `output/`) check an `available`/`_available` flag before acting and no-op gracefully if the underlying tool is missing; subprocess calls wrapped for `CalledProcessError`, `TimeoutExpired`, `FileNotFoundError` with explicit timeouts and `DEVNULL` stdio (`src-audio.md`).

## Threading & concurrency

- `Session` guards all state with an `RLock` shared with hotkey-listener callbacks (`src-core.md`).
- Generation counters (`_pending_generation` in the hotkey state machine, `_cancel_generation` in Session) invalidate stale timeouts/callbacks after a state transition supersedes them (`src-hotkey.md`, `src-core.md`).
- `queue.Queue` for thread-safe job/utterance pipelines; `threading.Event` for cancel/abort signals; `threading.Timer` for idle-unload and double-tap windows (`src-asr.md`, `src-core.md`, `src-hotkey.md`).
- `LazyModel` holds a `weakref` to its `Worker` to permit cleanup without a circular reference (`src-asr.md`).

## Release process

- Develop on `dev`; merging `dev` → `main` triggers `.github/workflows/release.yml` (lint, test, build, publish `v<version>` GitHub Release) (`root.md`).
- Every merge to `main` must bump `[project].version` in `pyproject.toml` — the release workflow refuses to reuse an existing version tag (`root.md`, `.github.md`).
- Release notes auto-generated from `git log <prev-tag>..v${VERSION} --oneline` (`.github.md`).
- `release-badge.yml` updates a shields.io JSON badge on an orphan `badges` branch after each release, committed as `github-actions[bot]` (`.github.md`).

## Testing conventions

See `testing.md` for full detail; key conventions: `pytest` with an `integration` marker (opt-in, `STENOGRAPHER_INTEGRATION=1`), helper functions instead of fixtures for building test prerequisites (`_cfg()`, `_make_session()`), and fake/mock objects (`_FakeDevice`, `_FakeRecorder`) over real hardware (`tests.md`).

## Open Questions

- The exact enforcement mechanism for "system libraries not bundled" (spec comment) — is it verified anywhere in CI, or purely convention? (`packaging.md`)
- Type-checking (mypy/pyright) is noted elsewhere as a "future addition" with no adoption yet — no target date found in scout reports (`root.md`).
