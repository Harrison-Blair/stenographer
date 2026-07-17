---
generated: 2026-07-17T01:39:59Z
commit: 939420f205b102d61ab3d7ed257a1680a61483dc
agent: fledge-forager
fledge_version: 0.5.8
---

# Conventions

Naming, error-handling, layering, and style conventions observed across stenographer's source, tests, packaging, and CI, reconciled where scout reports overlapped.

## Licensing & style

- Every source file (Python, shell, YAML) carries `# SPDX-License-Identifier: GPL-3.0-or-later` at the top (root:CLAUDE.md; observed in every scouted module — github.md, packaging.md, scripts.md, src-*.md).
- ruff: line length 100, target py314, rules `E,F,I,B,UP,N,SIM,RUF` (pyproject.toml, root.md).
- src-layout: package at `src/stenographer/`; `tests/` mirrors it file-for-file (root.md, modules.md).
- Shell scripts: `#!/usr/bin/env bash` + `set -euo pipefail` throughout (scripts.md, packaging.md).
- Python scripts: `#!/usr/bin/env python3` shebang; `from __future__ import annotations` + `TYPE_CHECKING` forward refs used in ASR/output modules (src-asr.md, src-output.md).

## Error handling

- All components MUST raise `StenographerError` subclasses (`ConfigError`, `CapabilityError`, `AudioCaptureError`, `TranscriptionError`, `UpdateError`) and use `errors.py`'s `notify_failure()` / `fatal()` / `degrade_capability()` rather than inventing ad-hoc error behavior (root:CLAUDE.md, src-cli.md).
- Exit-code convention: 78 (`EX_CONFIG`) for config/capability errors (`doctor`, `run`, `dictate`, `transcribe` fail fast when a required capability is missing); 1 for runtime/update errors (src-cli.md).
- `ConfigError` carries `(path, key, reason)` for precise messages, e.g. `"~/.config/stenographer/config.toml: hotkey.binding: must be a non-empty string"` (src-cli.md, root.md).
- Output/audio components (`Injector`, `ClipboardManager`, `Feedback`, `DesktopNotification`) take an `available: bool` capability flag at construction; on unavailability, methods return `False`/`None` and log rather than raise — graceful degradation, not crash (src-output.md, src-audio.md, src-cli.md).
- Subprocess-calling code (inject.py, clipboard.py) catches an explicit tuple `(CalledProcessError, TimeoutExpired, FileNotFoundError)` at every call site, logging returncode/stderr/exception type (src-output.md).
- Session-level: worker/injector/clipboard/feedback exceptions are caught, logged, and never re-raised from the processing loop; `contextlib.suppress` used for non-critical operations (src-session-live.md).

## Concurrency & locking

- `Session._lock` (RLock) is the single lock guarding all state transitions (`_recording`, `_recording_streamer`, `_live_streamer`, `_cancel_generation`, etc.); PortAudio callback threads and the hotkey listener thread touch only thread-safe queues or briefly-locked buffers, never block on `Session._lock` for long operations (src-session-live.md).
- Generation counters guard against stale async work: `Session._cancel_generation` (bumped by `cancel_all()`, drops stale queue items), `HotkeyStateMachine._pending_generation` (invalidates stale double-tap timers), `LazyModel._load_generation` (drops stale idle-unload requests) — the same pattern recurs in session.py, hotkey/state_machine.py, and asr/model.py (src-session-live.md, src-hotkey.md, src-asr.md).
- Daemon threads throughout (`daemon=True`) for background work (hotkey reader/supervisor threads, notification worker thread, ASR worker thread) so they don't block process shutdown (src-hotkey.md, src-cli.md, src-asr.md).
- Pure logic is kept out of threads: `hotkey/state_machine.py::HotkeyStateMachine` and `asr/streaming.py::StreamingTranscriber` are both explicitly "pure" (no I/O, fully testable in isolation) — the listener/live-streamer wrap them and perform actual I/O (src-hotkey.md, src-asr.md).

## Config conventions

- All config dataclasses are **frozen** (immutable), validated once on load (`Config.load()` in config.py); enum-like fields use `frozenset` allow-lists, e.g. `ALLOWED_TRIGGER_MODES = frozenset({"hybrid", "toggle"})`, `ALLOWED_COMPUTE_TYPES`, `ALLOWED_INJECTION_METHODS` (src-cli.md, src-hotkey.md).
- TOML bare `null` is rewritten to `""` on load since TOML 1.0 has no null type, letting users blank optional keys (src-cli.md).
- Config resolution order: `$STENOGRAPHER_CONFIG` → `$XDG_CONFIG_HOME/stenographer/config.toml` → write defaults on first start (root.md).

## Path / asset resolution

- PyInstaller onedir vs. wheel-install path resolution is handled via `sys.frozen` + `sys._MEIPASS` checks (`_resolve_asset_root()`/`_resolve_icon_root()` in cli.py), falling back to module-relative paths for source installs (src-cli.md).
- Scripts resolve the repo root relative to their own location (`dirname "$0"` in bash, `Path(__file__).resolve().parent.parent` in Python) rather than assuming CWD (scripts.md).
- Asset override resolution follows a fixed chain: explicit override dict → bundled `assets/sounds/` → log-and-skip (src-audio.md).

## Testing conventions

See `testing.md` for the full breakdown; key repo-wide patterns: `@pytest.mark.integration` gates any test touching real audio/clipboard/display, skipped by default and requiring `STENOGRAPHER_INTEGRATION=1`; helper naming `_make_*`/`_fake_*`/`_cfg()`/`_completed()` recurs across test files; `unittest.mock.patch` context managers over `subprocess.run`/hardware I/O (tests.md).

## CI / release conventions

- Concurrency groups with `cancel-in-progress` on CI and release-badge workflows (github.md).
- Release tags are `v${VERSION}`; every merge to `main` must bump `[project].version` in `pyproject.toml` or the release workflow refuses to republish an existing tag (root:CLAUDE.md, github.md).
- Pre-commit hook runs `ruff format` on staged `.py` files only, re-staging them; installed via `scripts/install-hooks.sh` setting `core.hooksPath` (github.md, scripts.md).

## Open Questions

- Whether pre-existing dead code exists outside the specifically scouted files was not assessed (src-session-live.md).
- Whether `set -euo pipefail` in the pre-commit hook causes commit abort on a ruff-format failure, or whether re-staging masks it (github.md).
