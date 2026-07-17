---
generated: 2026-07-17T01:39:59Z
commit: 939420f205b102d61ab3d7ed257a1680a61483dc
agent: fledge-forager
fledge_version: 0.5.8
---

# Dependencies

External libraries, system tools, and services stenographer depends on, deduplicated across modules with usage notes.

## Python runtime dependencies (`pyproject.toml [project.dependencies]`)

| Package | Used for |
|---|---|
| `sounddevice>=0.4.7` | PortAudio bindings; `audio/capture.py::Recorder` mic capture, `cli.py cmd_devices` device listing |
| `numpy>=2.0` | Audio array ops throughout (capture, ASR word/segment arrays, bench WER) |
| `faster-whisper>=1.0.0` | Offline ASR engine (CTranslate2/ONNX Runtime); wrapped by `asr/model.py::Model`/`LazyModel` |
| `evdev>=1.4` | Hotkey binding from `/dev/input/event*`; `hotkey/listener.py`, `hotkey/binding.py` |
| `soundfile>=0.12` | WAV cue file I/O (`audio/feedback.py` assets, `scripts/gen_cues.py`, `cli.py bench`) |
| `packaging>=24.0` | Semantic version parsing/comparison in `update.py` |
| `certifi>=2024.0` | CA bundle for SSL (update.py `_http_get`, HuggingFace downloads) |
| `huggingface_hub>=0.23` | ASR model downloads (`cli.py cmd_model_download`, `scripts/download_model.py`, `capabilities.py` model-cache check) |
| `argcomplete>=3.5` | Bash/zsh tab-completion for the `stenographer` CLI (`_parser.py`, `packaging/stenographer-completion.bash`) |

## Dev dependencies (`[project.optional-dependencies].dev`)

`ruff>=0.5` (lint+format), `pytest>=8` (test runner), `pytest-asyncio>=0.23` (async test support, available but most tests are synchronous — src-session-live.md).

## Build dependencies (`[project.optional-dependencies].build`)

`pyinstaller>=6.10` — bundles the CLI into a standalone `--onedir` binary (~370 MB on x86_64) via `packaging/stenographer.spec`; excludes native audio libs via `packaging/hook-sounddevice.py` and relinks them at runtime via `packaging/rthooks/py_rth_portaudio.py`.

## System tools (required at runtime, not bundled)

| Tool | Package | Used for |
|---|---|---|
| `wtype` | — | Wayland text injection; `output/inject.py::Injector.type_text()` and `.paste()` |
| `wl-copy` / `wl-paste` | `wl-clipboard` | Wayland clipboard write/read; `output/clipboard.py::ClipboardManager` |
| `pw-play` | `pipewire-audio` / pipewire-utils | Audio cue playback (preferred) |
| `paplay` | `pulseaudio-utils` | Audio cue playback (fallback) |
| `notify-send` | `libnotify-bin` | Desktop notifications; no-op if absent (`notification.py`) |
| `libportaudio2` / `portaudio` | — | PortAudio runtime for `sounddevice` |
| `libevdev1` / `libevdev` | — | evdev runtime; also needs C headers at build time for the Python 3.14 wheel |
| `systemctl` (systemd, user-level) | — | Daemon lifecycle (`cli.py cmd_enable/disable/start/stop`, `update.py stop_daemon/start_daemon`) |
| `gh` CLI | — | Used by CI (`release.yml`) to check/publish GitHub Releases, not needed at runtime |

Runtime capability presence is centrally probed by `capabilities.py::Capabilities.probe()` and surfaced via `stenographer doctor` (exits 78 if a required capability is missing).

## GitHub Actions (CI-only, `.github/workflows/`)

`actions/checkout@v7`, `actions/setup-python@v6`, `softprops/action-gh-release@v3` (github.md).

## ASR model (fetched separately, not bundled)

`Systran/faster-distil-whisper-medium.en` (~800 MB default; benchmarked against `Systran/faster-whisper-large-v3` as the WER gold reference in `bench.py`) — fetched via `stenographer model download` (huggingface_hub `snapshot_download`), cached, never bundled in the binary or wheel.

## Test-only dependencies

`unittest.mock` (stdlib), `pytest-mock` (monkeypatch), `caplog`/`tmp_path` (pytest built-ins) — see `testing.md`.
