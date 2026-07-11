---
generated: 2026-07-11T05:16:32Z
commit: f5694b5bffd265badb03101b726304b5e6a0efb4
agent: fledge-forager
fledge_version: 0.4.0
---

# Entry Points

How to run, build, and interact with the project; the boundaries components expose to each other.

## CLI (`stenographer.cli:main`, declared in `pyproject.toml [project.scripts]`)
Argument parsing lives in `_parser.py` (kept import-light for the argcomplete hot path); heavy imports (faster-whisper, sounddevice) are deferred into each `cmd_*` handler in `cli.py`.

Subcommands:
- `run` — foreground daemon; holds a single-instance `fcntl.flock` on `$XDG_RUNTIME_DIR/stenographer.lock`; builds the full `Session` via `cli.py:_build_session()` and blocks on `Session.run()`.
- `dictate` — one-shot arm/dictate/exit (`Session(one_shot=True)`), used for scripted/manual single-utterance invocation.
- `transcribe FILE` — batch transcription of an existing audio file (no hotkey/recorder involved).
- `bench` — offline ASR benchmarking harness (`bench.py:run()`); compares (model × beam × compute_type) tuples on load time, RTF, WER.
- `model download` — fetches the ASR model via `huggingface_hub.snapshot_download` (also available standalone as `scripts/download_model.py`).
- `update [--check]` — self-update from GitHub Releases (`update.py`).
- `doctor` — runs `Capabilities.probe()` and reports; exits 78 if a required capability is missing.
- `devices` — lists audio input devices (sounddevice query).
- `enable` / `start` / `stop` / `disable` — systemd user-unit lifecycle management.
- `--version` — prints `__version__` (from `importlib.metadata`, falls back to `"0.0.0+unknown"`).

Exit codes: `0` success, `1` runtime error, `2` usage error, `78` (EX_CONFIG) config/capability error.

## Session boundary (`session.py:Session`)
Constructed by `cli.py:_build_session(cfg, caps, one_shot)`, given: `cfg`, `capabilities`, `listener` (may be late-bound via `attach_listener()`), `recorder`, `worker`, `feedback`, `injector`, `clipboard`, `notification=None`, `one_shot=False`.
Public surface: `attach_listener()`, `start_listener()`, `start()`, `run()`, `stop()`; properties `stop_event`, `is_one_shot`, `lock`, `notification`; hotkey callbacks `on_recording_start()`, `on_recording_stop(mode)`, `on_toggle_off()`, `discard_recording()`, `cancel_all()`.

## Component boundaries (constructor-injected into Session — the seams a new mode/output plugs into)
- **`hotkey.HotkeyListener`** — `start()`, `stop(timeout=2.0)`, `is_running`; invokes `on_start`/`on_stop`/`on_toggle_off`/`on_discard`/`on_cancel` callbacks under an optional shared `RLock`.
- **`hotkey.HotkeyBinding`** — `HotkeyBinding.parse(s)`, `.to_evdev_codes()`, `.matches(event_keys)`.
- **`audio.Recorder`** — `start(on_segment=None, on_partial=None, min_partial_seconds=1.0)`, `stop() -> np.ndarray`, `snapshot(start_seconds=0.0) -> np.ndarray`, `is_active`, `default_input_device_name()`.
- **`audio.Feedback`** — `play(name: CueName)`, `close()`.
- **`asr.LazyModel` / `asr.Model`** — `ensure_loaded()`, `is_loaded()`, `close()`, `transcribe()`, `transcribe_words()`, `attach_worker()`; properties `language`, `beam_size`.
- **`asr.Worker`** — `start()`, `submit()` (batch), `submit_words()` (word-timestamped re-decode), `request_unload()`, `cancel()`, `stop()`, `ensure_model_loaded()`, `is_model_loaded()`; property `is_running`.
- **`asr.streaming.StreamingTranscriber`** — pure LocalAgreement-N committer (not directly injected into Session; used inside `live.py:LiveStreamer`).
- **`live.LiveStreamer`** — constructed with `cfg, recorder, worker, injector, transcriber, formatter, clipboard, caps, abort`; `run() -> str`, `signal_partial()`, `signal_final(samples)`, `signal_abort()`.
- **`output.Injector`** — `type_text(text, raw=False) -> bool`, `paste() -> bool`, `close()`.
- **`output.ClipboardManager`** — `copy(text) -> bool`, `read() -> str | None` (test-only), `close()`.
- **`output.HeuristicFormatter`** — `feed(tokens) -> str` (incremental), `finalize() -> str`, `reset()`, `format_batch(tokens) -> str` (one-shot).
- **`notification.DesktopNotification`** — `show_startup(binding)`, `show_listening()`, `show_transcribing()`, `show_model_loading()`, `show_model_unloaded()`, `hide()`, `flush()`; `DesktopNotification.probe()`.

## Config entry point (`config.py`)
- `Config.defaults() -> Config`
- `Config.load(path) -> Config`
- `Config.write_default(path)` — writes the default TOML on first run.
- Resolution order: `$STENOGRAPHER_CONFIG` env → `$XDG_CONFIG_HOME/stenographer/config.toml` (default `~/.config/stenographer/config.toml`).

## Capabilities entry point (`capabilities.py`)
- `Capabilities.probe(cfg) -> Capabilities`.

## Update entry points (`update.py`)
- `check_for_update(cfg, current_version=None, prerelease=False) -> UpdateInfo | None`
- `download_update(info, cfg, staging_dir=None) -> Path`
- `extract_to_staging(tarball, install_root) -> Path`
- `apply_update(bundle, install_root)`
- `stop_daemon() -> bool`, `start_daemon() -> bool`

## systemd integration
User-level unit at `~/.config/systemd/user/stenographer.service` (rendered from `packaging/stenographer.service.in`; `Type=simple`, `ExecStart=%h/.local/share/stenographer/stenographer run`, `Restart=on-failure`, binds to `graphical-session.target`, depends on `pipewire.service`/`pulseaudio.service`). Registered by the `enable` CLI subcommand or manually.

## Build / install entry points
- `scripts/build.sh` → `dist/stenographer/stenographer` (PyInstaller `--onedir` via `packaging/stenographer.spec`).
- `scripts/install.sh [--no-enable] [--no-start] [--install-dir DIR]` — full source install (build, install to `~/.local/share/stenographer/`, symlink, completion, systemd).
- `scripts/build-and-install.sh [ARGS]` — wrapper forwarding to both.
- `packaging/install.sh` — curl-pipeable installer for prebuilt GitHub Release binaries (flags `--version`, `--yes`, `--no-deps`; env overrides `STENOGRAPHER_REPO`, `STENOGRAPHER_VERSION`).
- `scripts/install-hooks.sh` — one-shot git hook configuration (`core.hooksPath .githooks`).

## Release entry point
Merge `dev` → `main` triggers `.github/workflows/release.yml` (lint → test → build → publish `v<version>` release); requires `[project].version` in `pyproject.toml` bumped beforehand (workflow refuses to reuse a release tag).
