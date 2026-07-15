---
generated: 2026-07-15T17:38:33Z
commit: d621b46261d9509fccbdffc4686be0b876c7951e
agent: fledge-forager
fledge_version: 0.5.4
---

# Entry Points

Where to start reading for each user- or developer-facing surface: the CLI, its subcommands, public component APIs, and how to build/install/run the project.

## CLI entry point

`stenographer` command (`[project.scripts]` in `pyproject.toml`) → `stenographer.cli:main`. `main(argv)` in `cli.py` parses args (via the separate lightweight `_parser.py`, kept import-light for the argcomplete hot path), handles `--config`/`--version`, and dispatches to `cmd_*` functions (`root.md`, `src-core.md`).

### Subcommands

- `run` — foreground daemon; holds a `fcntl.flock` on `$XDG_RUNTIME_DIR/stenographer.lock` for single-instance enforcement.
- `dictate` — one-shot: arm, dictate, exit.
- `transcribe FILE` — batch mode, formatted or `--raw` output.
- `model download [--repo-id ...]` — fetches the ASR model (~800 MB) via `huggingface_hub`.
- `bench` — ASR benchmarking harness (word error rate, RTF across model/beam/compute_type matrix).
- `update [--check]` — self-update from GitHub Releases.
- `doctor` — probes capabilities (`Capabilities.probe()`) and prints resolved config; exits 78 if a required capability is missing.
- `devices` — lists audio devices.
- `enable`/`disable`/`start`/`stop` — systemd user-service management (deprecated `run stop`/`run disable` syntax detected and rejected).
- `--version` — prints package version.

## Component public interfaces

- **`Session`** (`session.py`) — constructed by `cli.py`'s `run`/`dictate` paths; callbacks `on_recording_start`/`on_recording_stop`, `discard_recording`, `cancel_all`; queues batch/live utterances to an internal processor thread (`src-core.md`).
- **`LiveStreamer`** (`live.py`) — streams partials through `worker.submit_words`, LocalAgreement committer, formatter, typed delta with tail-silence guard and sentence-boundary trim.
- **`Config`** (`config.py`) — `Config.load(path)`, `Config.defaults()`, `Config.write_default(path)`; raises `ConfigError` with dotted key path on invalid values.
- **`Capabilities`** (`capabilities.py`) — `Capabilities.probe(cfg)` static method, returns a frozen instance.
- **`HotkeyListener`/`HotkeyBinding`/`HotkeyStateMachine`** (`hotkey/`) — see `architecture.md` for wiring; `auto_detect_paths()`/`auto_detect_path()` scan `/dev/input/event*` for keyboard-like devices.
- **`Recorder`** (`audio/capture.py`) — `start(*, on_segment=None, on_partial=None, ...)`, `stop() -> np.ndarray`, `snapshot(start_seconds=0.0) -> np.ndarray`, `is_active`, `default_input_device_name()`.
- **`Feedback`** (`audio/feedback.py`) — `play(name: CueName)`, `close()`.
- **`Injector`** (`output/inject.py`) — `type_text(text, *, raw=False) -> bool`, `paste() -> bool`, `close()`.
- **`ClipboardManager`** (`output/clipboard.py`) — `copy(text) -> bool`, `read() -> str | None`, `close()`.
- **`HeuristicFormatter`** (`output/formatter.py`) — `feed(tokens) -> str` (streaming), `format_batch(tokens) -> str` (batch), `finalize()`, `reset()`.
- **`Model`/`LazyModel`** (`asr/model.py`) — `transcribe(...)`, `transcribe_words(...)`, `close()`; `LazyModel.ensure_loaded(on_loaded=None, on_unloaded=None)`.
- **`Worker`** (`asr/worker.py`) — `start()`, `submit(...)`, `submit_words(...)`, `cancel()`, `stop(timeout=30)`.
- **`StreamingTranscriber`** (`asr/streaming.py`) — `insert(hypothesis)`, `flush()`, `rebase(dropped_seconds)`, `reset()`.
- **`update` module** (`update.py`) — `check_for_update`, `download_update`, `extract_to_staging`, `apply_update`, `detect_install_root`, `stop_daemon`, `start_daemon`, `acquire_update_lock`.
- **`DesktopNotification`** (`notification.py`) — `show_startup`, `show_listening`, `show_transcribing`, `show_rewriting`, `show_prompt_ready`/`show_prompt_failed`, `show_model_loading`/`show_model_unloaded`.

## Build / install / run

- **Recreate the dev venv**: `python3 -m venv .venv && .venv/bin/pip install -e ".[dev,build]"` — never use system `python`/`pip`/`ruff`/`pytest` (CLAUDE.md, root.md).
- **Lint/format**: `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`.
- **Unit tests**: `.venv/bin/pytest -m "not integration"`.
- **All tests**: `STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest`.
- **Build standalone binary**: `scripts/build.sh` → wraps `pyinstaller --noconfirm --clean packaging/stenographer.spec` → `dist/stenographer/stenographer` (onedir, ~370 MB).
- **Full source install**: `scripts/install.sh` — builds if missing, copies to `~/.local/share/stenographer/`, symlinks launcher into `~/.local/bin/`, installs bash completion, generates + enables systemd user unit. Options: `--no-enable`, `--no-start`, `--install-dir DIR`.
- **Convenience wrapper**: `scripts/build-and-install.sh` — `build.sh` then `install.sh`, passing through args.
- **End-user install (prebuilt binary)**: `curl -fsSL https://github.com/Harrison-Blair/stenographer/releases/latest/download/install.sh | bash` (or `packaging/install.sh` downloaded from a release) — verifies SHA-256, checks system deps, joins `input` group, generates config, downloads ASR model, enables systemd service.
- **Enable git hooks**: `scripts/install-hooks.sh` (run once after cloning) — points `git` at `.githooks/` so `ruff format` runs pre-commit.
- **CI entry points**: `.github/workflows/ci.yml` (PR gate: lint, test, build), `.github/workflows/release.yml` (push-to-main: version extraction, build, GitHub Release publish), `.github/workflows/release-badge.yml` (post-release badge update).

## Open Questions

- Does `scripts/build.sh`'s `pyinstaller --noconfirm --clean` fully rebuild `dist/` each time, or does PyInstaller cache incrementally? Affects local rebuild latency (`scripts.md`).
- If `scripts/build.sh` fails during the release workflow, does it halt before GitHub Release creation (preventing a partial/broken release)? (`.github.md`)
