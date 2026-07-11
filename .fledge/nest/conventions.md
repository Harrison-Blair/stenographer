---
generated: 2026-07-11T05:16:32Z
commit: f5694b5bffd265badb03101b726304b5e6a0efb4
agent: fledge-forager
fledge_version: 0.4.0
---

# Conventions

Coding, tooling, and process conventions observed across the repository, reconciled across modules.

## Licensing & headers
- Every `.py` file (source, scripts, and PyInstaller hooks) starts with `# SPDX-License-Identifier: GPL-3.0-or-later`.
- CI workflow YAML files also carry the SPDX header.

## Linting & formatting
- `ruff` line-length 100, `target-version py314`, rule set `["E", "F", "I", "B", "UP", "N", "SIM", "RUF"]` (`pyproject.toml [tool.ruff]`).
- Pre-commit hook (`.githooks/pre-commit`, enabled via `scripts/install-hooks.sh` → `git config core.hooksPath`) auto-formats staged `.py` files with ruff and re-stages them; looks up `.venv/bin/ruff` before falling back to system `ruff`.
- CI (`release.yml` `lint-test` job) runs `ruff check` and `ruff format --check` before tests.

## Layout
- src-layout: `src/stenographer/`. `tests/` mirrors it file-for-file (`test_<module>.py` ↔ `<module>.py`).
- `pyproject.toml` (hatchling backend) is the single source of truth for metadata, runtime/dev/build dependencies, entry point, and wheel-included assets (`assets/sounds/*.{wav,ogg}`, `assets/icons/*.png`).

## Error handling policy
- All components raise `StenographerError` subclasses (`errors.py`): `ConfigError`, `CapabilityError`, `AudioCaptureError`, `TranscriptionError`, `UpdateError`. Never invent ad hoc error behavior.
- Three policy functions gate what happens on failure: `notify_failure()` (log ERROR, continue), `fatal()` (log CRITICAL, `sys.exit(78)` default — EX_CONFIG), `degrade_capability()` (log WARNING, continue with reduced functionality).
- `doctor` subcommand and `run`/`dictate` capability checks exit 78 when a *required* capability (input group, mic, ASR model) is missing; optional capabilities (wtype, wl-copy, notify-send) degrade gracefully with a WARNING and the daemon continues.

## Threading & concurrency
- Reentrant locks (`threading.RLock`) protect shared mutable state where callbacks may re-enter (e.g. `Session._lock` shared with the hotkey listener's dispatch path; `LazyModel`'s internal RLock).
- Generation counters are the repo's standing pattern for invalidating stale async work rather than cancellation exceptions: `Session._cancel_generation` (queue items), `LazyModel._load_generation` (idle-unload requests), `HotkeyStateMachine._pending_generation` (double-tap timeout callbacks).
- Callbacks invoked directly from a non-owning thread (e.g. the PortAudio callback thread calling `Session._enqueue_flush_segment`) deliberately avoid taking the shared lock — they touch only thread-safe primitives (`queue.Queue`) and plain-read attributes, and must stay non-blocking.
- Off-main-thread work (ASR transcription, model unload) goes through a dedicated worker thread with a job queue, never as a fire-and-forget `Thread` per call.

## Dataclasses & immutability
- Value/result types are frozen dataclasses: `SegmentInfo`, `WordInfo`, `TranscriptionResult` (asr/model.py), `Capabilities`, `UpdateInfo`, `Config` and its nested sub-configs.
- "Committed"/immutable-once-set semantics recur deliberately: `StreamingTranscriber`'s committed prefix is never revised; typed output in the live path is likewise never revised (an explicit invariant documented in `live.py`).

## Naming & style
- Private members prefixed `_`, no double-underscore name mangling.
- `Literal` types for closed string enums (`CueName`, hotkey `State`/`Action`, `AsrConfig.mode`, `OutputConfig.injection_method`).
- `NamedTuple` for small immutable return bundles (`Transition`).
- Public API surfaced through package `__init__.py` exports (`hotkey/__init__.py`, `asr/__init__.py`); internal helpers stay unexported.

## Config
- TOML, loaded once at startup. `Config.defaults()` is the single source of truth for default values; `Config.load(path)` parses, validates per-section (`_build_hotkey`, `_build_audio`, etc.), and merges with defaults.
- Resolution order: `$STENOGRAPHER_CONFIG` env override → `$XDG_CONFIG_HOME/stenographer/config.toml` (default `~/.config/stenographer/config.toml`); default TOML written on first run.
- `null` TOML values are rewritten to `""` at load time so users can explicitly blank an optional string key.

## Logging
- Module-level `logger = logging.getLogger(__name__)` per file; log messages prefixed with a context marker, e.g. `"session: ..."`, `"output.inject: ..."`.
- stderr + `RotatingFileHandler` at `$XDG_STATE_HOME/stenographer/stenographer.log` (default `~/.local/state/stenographer/`); level overridable via `STENOGRAPHER_LOG_LEVEL` env.
- DEBUG for routine events (keypresses, resampling fallbacks), WARNING/ERROR for degraded capabilities and failures.

## Process/build
- Bash scripts (`scripts/*.sh`, `packaging/install.sh`) uniformly use `set -euo pipefail`, `cd "$(git rev-parse --show-toplevel)"` or `cd "$(dirname "$0")"` for path independence, and dedicated `err()/warn()/ok()/info()` helper functions with ANSI colors (stripped if not a TTY).
- All Python tooling invoked through `.venv/bin/...` — never system `python`/`pip`/`ruff`/`pytest` (CLAUDE.md, scripts/build.sh).
- Standalone binary: PyInstaller `--onedir` via `packaging/stenographer.spec`; `_resolve_asset_root()`/`_resolve_icon_root()` in `cli.py` handle both wheel-install and frozen-binary asset paths.

## Release process
- Develop on `dev`; merge to `main` triggers `.github/workflows/release.yml` (lint → test → build → publish `v<version>` GitHub Release via `softprops/action-gh-release@v3`).
- The workflow refuses to reuse an existing release tag — **every merge to `main` must bump `[project].version` in `pyproject.toml`** first.
- Release notes generated from `git log` since the previous tag.

## Tests
- pytest (+ `pytest-asyncio`) exclusively; one `test_<module>.py` file per source module, mirroring `src/stenographer/` layout.
- `integration` marker for tests touching real clipboard/audio/display — skipped by default, run via `STENOGRAPHER_INTEGRATION=1`.
- Heavy use of `unittest.mock.MagicMock` to isolate components (e.g. `test_session.py` mocks Recorder, Worker, Injector, Clipboard, Feedback, Listener entirely).
- Assertions via `assert_called_once_with()`, `assert_not_called()`, etc.; fixtures follow a `_make_x()` / `_fake_x()` naming convention.
