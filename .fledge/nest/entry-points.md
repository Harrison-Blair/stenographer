---
generated: 2026-07-17T01:39:59Z
commit: 939420f205b102d61ab3d7ed257a1680a61483dc
agent: fledge-forager
fledge_version: 0.5.8
---

# Entry Points

CLI subcommands, public component interfaces, and how to run/build the project.

## CLI (`src/stenographer/cli.py::main(argv=None)`)

Console-script entry point; dispatches subcommands via `_parser.py`'s argparse builder (kept import-light for the argcomplete hot path):

- `run` — start the daemon: probes capabilities, acquires single-instance `fcntl.flock` on `$XDG_RUNTIME_DIR/stenographer.lock`, builds a `Session` via `_build_session()`, installs signal handlers, starts the hotkey listener.
- `dictate` — one-shot dictation (`one_shot=True` disables mid-recording silence flushing).
- `transcribe FILE` — batch-transcribe an audio file; `--raw` skips formatting.
- `bench` — ASR benchmarking harness (model × beam × compute-type matrix; WER vs. gold, RTF, cold-load time).
- `model download` — fetch the ASR model via `huggingface_hub.snapshot_download`.
- `update [--check|--yes|--no-restart|--prerelease]` — self-update from GitHub Releases.
- `doctor` — capability probe + config echo; **exits 78** if a required capability is missing.
- `devices` — list audio input devices.
- `enable` / `disable` / `start` / `stop` — systemd user-unit management (fast path, no config load required).

## Session (`src/stenographer/session.py::Session`)

The programmatic orchestrator entry point once wired by `_build_session()`:

- `start()` / `run()` / `stop()` — lifecycle: launch processor thread, block until `stop()`, shutdown (drains queue, stops listener/worker/feedback/injector/clipboard/notification).
- `on_recording_start(source="dictate")` / `on_recording_stop(mode, source="dictate")` / `on_toggle_off()` / `discard_recording()` — hotkey-listener callbacks.
- `cancel_all()` — cancel recording, drain queue, abort in-flight transcription, wake any live streamer.
- `attach_listener(listener)` — late-bind the hotkey listener after construction.

## LiveStreamer (`src/stenographer/live.py::LiveStreamer`)

- `run() -> str` — consumer loop; returns final typed text.
- `signal_partial()` / `signal_final(samples)` / `signal_abort()` — fired from the recorder/session side.

## Component public APIs (see `modules.md` / `data-model.md` for full listings)

- **Hotkey**: `HotkeyBinding.parse(s)`, `HotkeyListener.start()/stop()`, `HotkeyStateMachine.on_keydown()/on_keyup()/on_timeout()/on_cancel()`, `auto_detect_paths()`.
- **Audio**: `Recorder.start(on_segment=..., on_partial=...)`, `.stop() -> ndarray`, `.snapshot(start_seconds) -> ndarray`; `Feedback.play(name: CueName)`.
- **ASR**: `Model.transcribe()` / `.transcribe_words()`; `LazyModel.ensure_loaded()` / `.is_loaded()`; `Worker.submit()` / `.submit_words()` / `.cancel()`; `StreamingTranscriber.insert()` / `.flush()` / `.rebase()`.
- **Output**: `Injector.type_text(text, raw=False)` / `.paste()`; `ClipboardManager.copy(text)` / `.read()`; `HeuristicFormatter.feed(tokens)` / `.finalize()` / `.format_batch(tokens)`.
- **Config**: `Config.load()` / `Config.defaults()` / `resolve_config_path()` / `load_or_default()`.
- **Capabilities**: `Capabilities.probe(cfg) -> Capabilities`.

## How to run / build (see root CLAUDE.md for authoritative commands)

- Dev venv: `python3 -m venv .venv && .venv/bin/pip install -e ".[dev,build]"` — never use system `python`/`pip`/`ruff`/`pytest`.
- Lint/format: `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`.
- Unit tests: `.venv/bin/pytest -m "not integration"`; all tests: `STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest`.
- Build standalone binary: `scripts/build.sh` → `dist/stenographer/stenographer` (wraps `pyinstaller --noconfirm --clean packaging/stenographer.spec`).
- Full source install: `scripts/install.sh` (builds, installs to `~/.local/share/stenographer/`, symlinks to `~/.local/bin/`, installs systemd user unit, enables it).
- Git hooks (ruff format on commit): `./scripts/install-hooks.sh`.

## Release entry point

Merging `dev` → `main` triggers `.github/workflows/release.yml` (lint, test, build, publish a `v<version>` GitHub Release); requires `[project].version` in `pyproject.toml` to be bumped, or the workflow refuses to republish an existing tag.
