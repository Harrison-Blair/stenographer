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

PyGObject is a mandatory dependency, so that install needs the distro's
GObject-introspection and Cairo development packages present; the overlay
additionally needs GTK4 and `gtk4-layer-shell` at runtime.

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
existing release, so **every merge to `main` must bump `__version__` in
`src/stenographer/_version.py`.**

## Architecture

The package is `src/stenographer/` (src-layout); `tests/` mirrors it.

**Entry point** — `cli.py` (`main`) dispatches subcommands: `run`, `dictate`,
`transcribe`, `model download`, `update`, `doctor`, `devices`, `bench`, plus
systemd management (`enable`/`start`/`stop`/`disable`). The argument parser
lives separately in `_parser.py` so the argcomplete hot path can build it
without the heavy imports. `run` holds a single-instance `fcntl.flock` on
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
  `state_machine.py` is a **pure** state machine implementing the three
  `hotkey.trigger_mode` values: `ptt` (the default — record while held),
  `toggle` (a press latches recording on, the next press stops it), and
  `hybrid` (≥`toggle_threshold_seconds` hold = push-to-talk, a short press
  followed by a second tap within `double_tap_window_seconds` latches toggle).
- **`audio/`** — `capture.py` (`Recorder`) captures mic audio via
  `sounddevice`/PortAudio with silence detection; `feedback.py` plays the WAV
  cues in `assets/sounds/` via `pw-play`/`paplay`.
- **`asr/`** — `model.py` wraps faster-whisper (`Model`, plus `LazyModel` which
  loads on first use and unloads after idle); `worker.py` runs transcription
  off the main thread with cancellation support: one batch job per utterance
  (`submit`) or one word-timestamped re-decode (`submit_words`);
  `streaming.py` is the **pure** LocalAgreement-N committer — a word joins the
  committed prefix only after N consecutive re-decodes agree on it; that prefix
  is append-only, while the latest uncommitted hypothesis is exposed as a
  revisable provisional tail.
- **`output/`** — `inject.py` (`Injector`, types via `wtype`),
  `clipboard.py` (`ClipboardManager`, via `wl-copy`), and `formatter.py`
  (`HeuristicFormatter`: spacing / capitalisation / pause-based paragraph
  breaks; append-only, so it is safe in the incremental path). The clipboard
  is populated independently, so it's the fallback when injection fails.
- **`live.py`** — `IncrementalDriver`, the incremental decoding driver
  (`[incremental]` config; always on for daemon recordings, not gated by a
  config flag or by `output.injection_method`): recorder partials → coalesce →
  `submit_words` re-decode → committer → formatter → preview callback, with
  tail-silence guarding and window trimming. **Invariant: it never writes to
  the clipboard or the focused application** — it returns one final transcript
  and `Session` delivers it exactly once. Everything it publishes en route is
  a preview (stable prefix + revisable provisional tail) rendered only in the
  overlay. `LiveStreamer` remains as a compatibility alias for the old name;
  new code uses `IncrementalDriver`.
- **`visualizer.py`** — `StatusIndicator`, the status HUD (`[visualizer]`
  config), wired by `cli.py` and driven by `Session` state transitions.
  `LayerShellOverlay` spawns a GTK4 layer-shell helper subprocess
  (`stenographer _visualizer`) and talks to it over JSON-lines on stdin;
  `SpectrumAnalyzer` does FFT band analysis on a dedicated thread fed by a
  one-slot queue, so the PortAudio callback only ever copies a block.
  `StatusIndicator` prefers the overlay and **transparently falls back** to
  `notification.py` when GTK, layer shell, or Wayland is unavailable — so
  nothing in the daemon may assume the overlay exists. Preview text goes to
  the overlay only; it is never sent to `notify-send`.

**Cross-cutting:**

- **`config.py`** — TOML config schema and loading (`Config` dataclass).
  `_validate_cross_section` enforces one invariant *at load time*, raising
  `ConfigError` rather than coercing: `output.injection_method =
  "clipboard_paste"` requires `clipboard.enabled`, because the clipboard is
  the paste transport rather than a convenience copy. Renamed keys are
  **migrated, not rejected**: `_build_output` maps the pre-0.9.2
  `text`/`paste` spellings onto `type`/`clipboard_paste` with a deprecation
  warning (`ALLOWED_INJECTION_METHODS` holds only the new names), and
  `_migrate_streaming_table` folds a legacy `[streaming]` table into
  `[incremental]`, warning that `streaming.enabled` is ignored since
  incremental decoding is now unconditional. That is the pattern to follow:
  a hard rejection fails `run` at startup and forces every existing config to
  be hand-edited, so weigh it against migrating with a warning.
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

The ASR model (~1.5 GB) is **never** bundled — users fetch it once with
`stenographer model download`.

## Conventions

- Every source file carries `SPDX-License-Identifier: GPL-3.0-or-later` at the top.
- ruff: line length 100, target py314, rules `E,F,I,B,UP,N,SIM,RUF`.
- `pyproject.toml` (hatchling) is the single source of truth for metadata/deps.
> fledge: load and follow .fledge/skills/fledge-orchestrate/SKILL.md — primitive map at .claude/fledge-adapter.md
