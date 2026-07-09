# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`stenographer` is a Wayland-only, local-only push-to-talk / toggle dictation
daemon. Press a global hotkey, speak, and the recognised text is typed at the
cursor (via `wtype`) and copied to the Wayland clipboard (via `wl-copy`).
Offline, English-only, GPL-3.0-or-later, Python ≥ 3.14.

## Commands

All Python tooling runs through the repo venv (`.venv/`, gitignored). **Never
use the system `python` / `pip` / `ruff` / `pytest`.** Recreate the venv with:

```sh
python3 -m venv .venv && .venv/bin/pip install -e ".[dev,build]"
```

- **Lint / format:** `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .`
  (`.venv/bin/ruff check --fix .` to autofix).
- **Test (unit):** `.venv/bin/pytest -m "not integration"`
- **Test (all, incl. env-touching):** `STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest`
- **Single test:** `.venv/bin/pytest tests/test_session.py::test_name`
- **Build standalone binary:** `scripts/build.sh` → `dist/stenographer/stenographer`
  (wraps `pyinstaller --noconfirm --clean packaging/stenographer.spec`).
- **Full source install:** `scripts/install.sh` (builds, installs to
  `~/.local/share/stenographer/`, symlinks launcher into `~/.local/bin/`,
  enables the systemd user unit).

`integration`-marked tests touch the real clipboard / audio / display and are
skipped unless `STENOGRAPHER_INTEGRATION=1` is set.

Run the git hooks once after cloning (`./scripts/install-hooks.sh`) so
`ruff format` runs on staged Python at commit time.

## Release / branch model

Develop on `dev`. Merging `dev` → `main` triggers
`.github/workflows/release.yml`, which lints, tests, builds the binary, and
**publishes** a `v<version>` GitHub release. The workflow refuses to reuse an
existing release, so **every merge to `main` must bump `[project].version` in
`pyproject.toml`.**

## Architecture

The package is `src/stenographer/` (src-layout); `tests/` mirrors it.

**Entry point** — `cli.py` (`main`) dispatches subcommands: `run`, `dictate`,
`transcribe`, `model download`, `update`, `doctor`, plus systemd management
(`enable`/`start`/`stop`/`disable`). The argument parser lives separately in
`_parser.py` so the argcomplete hot path can build it without the heavy
imports. `run` holds a single-instance `fcntl.flock` on
`$XDG_RUNTIME_DIR/stenographer.lock`.

**`session.py` — the orchestrator.** `Session` is the single point of state
transitions for one utterance: hotkey → record → transcribe → output. Every
callback from the hotkey listener, recorder, and worker funnels through
session methods guarded by a lock, so concurrent key events and shutdown
signals can't race. When wiring components together, this is the file that
ties them.

The component modules it wires:

- **`hotkey/`** — `binding.py` parses the config binding string; `listener.py`
  is the evdev read loop over `/dev/input/event*` (requires `input` group);
  `state_machine.py` is a **pure** state machine implementing the hybrid
  trigger (short press = toggle, ≥0.5s press = push-to-talk).
- **`audio/`** — `capture.py` (`Recorder`) captures mic audio via
  `sounddevice`/PortAudio with silence detection; `feedback.py` plays the WAV
  cues in `assets/sounds/` via `pw-play`/`paplay`.
- **`asr/`** — `model.py` wraps faster-whisper (`Model`, plus `LazyModel` which
  loads on first use and unloads after idle); `worker.py` runs transcription
  off the main thread with cancellation support; `streaming.py` is a
  **prototype** (LocalAgreement-N incremental decoding), not the daemon's
  current path — the daemon transcribes each utterance in one batch pass.
- **`output/`** — `inject.py` (`Injector`, types via `wtype`) and
  `clipboard.py` (`ClipboardManager`, via `wl-copy`). The clipboard is
  populated independently, so it's the fallback when injection fails.

**Cross-cutting:**

- **`config.py`** — TOML config schema and loading (`Config` dataclass).
- **`capabilities.py`** — the probe behind `doctor`: checks `wtype`, `wl-copy`,
  audio player, `input` group membership, mic, and the ASR model.
- **`errors.py`** — error-handling policy. Components MUST raise
  `StenographerError` subclasses and use `notify_failure` / `fatal` /
  `degrade_capability` rather than inventing their own error behaviour. `doctor`
  exits 78 when a required capability is missing.
- **`notification.py`** — desktop notifications via `notify-send` (no-op if absent).
- **`update.py`** — self-update from GitHub Releases (SHA-256 verify, onedir
  self-replace, daemon stop/start). The pure functions are unit-tested; `cli.py`
  wires them to the interactive prompt.

The ASR model (~800 MB) is **never** bundled — users fetch it once with
`stenographer model download`.

## Conventions

- Every source file carries `SPDX-License-Identifier: GPL-3.0-or-later` at the top.
- ruff: line length 100, target py314, rules `E,F,I,B,UP,N,SIM,RUF`.
- `pyproject.toml` (hatchling) is the single source of truth for metadata/deps.

## Note on AGENTS.md

`AGENTS.md` and several module docstrings reference a `spec/` directory as the
canonical source of truth. **That directory was removed** (commit `d4c0192`);
the spec no longer exists in the tree. Treat the code + tests as authoritative,
and don't follow AGENTS.md's "draft a spec doc first" workflow — the `spec/`
files it points to are gone. The `.venv`/tooling and release/branch guidance in
AGENTS.md is still accurate.
