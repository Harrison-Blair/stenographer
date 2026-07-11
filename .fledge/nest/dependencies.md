---
generated: 2026-07-11T05:16:32Z
commit: f5694b5bffd265badb03101b726304b5e6a0efb4
agent: fledge-forager
fledge_version: 0.4.0
---

# Dependencies

External libraries, tools, and services, deduplicated with usage notes.

## Python runtime dependencies (`pyproject.toml [project.dependencies]`)
- **sounddevice** (>=0.4.7) — PortAudio wrapper; mic capture in `audio/capture.py:Recorder`.
- **numpy** (>=2.0) — audio sample arrays (float32), RMS energy, resampling filters, WER computation in `bench.py`.
- **faster-whisper** (>=1.0.0) — CTranslate2-based offline ASR backend; `asr/model.py:Model` wraps `WhisperModel`. Model itself (~800 MB) is never bundled — fetched via `stenographer model download`.
- **evdev** (>=1.4) — reads `/dev/input/event*` for hotkey capture; requires the user be in the `input` group. Used in `hotkey/binding.py`, `hotkey/listener.py`.
- **soundfile** (>=0.12) — WAV/audio file I/O; used for cue loading (`gen_cues.py`) and benchmark clip loading (`bench.py`).
- **packaging** (>=24.0) — version parsing/comparison in `update.py`'s release-selection logic.
- **certifi** (>=2024.0) — TLS certificate bundle for self-update HTTPS downloads.
- **huggingface_hub** (>=0.23) — ASR model download/caching (`snapshot_download` in `scripts/download_model.py`; `try_to_load_from_cache` in `capabilities.py` to probe if the model is cached).
- **argcomplete** (>=3.5) — bash/zsh tab-completion for the CLI parser.

## Python dev dependencies (`[project.optional-dependencies.dev]`)
- **ruff** (>=0.5) — linter + formatter (100-char lines, rules E/F/I/B/UP/N/SIM/RUF).
- **pytest** (>=8) — test runner.
- **pytest-asyncio** (>=0.23) — async test support.

## Python build dependencies (`[project.optional-dependencies.build]`)
- **pyinstaller** (>=6.10) — builds the standalone `--onedir` binary (`scripts/build.sh`, `packaging/stenographer.spec`).

## External system CLIs (invoked via `subprocess`, probed by `Capabilities.probe`, never bundled)
- **wtype** — types text at the cursor (Wayland virtual keyboard protocol); used by `output/inject.py:Injector` (`type_text()`, `paste()`).
- **wl-copy** / **wl-paste** — Wayland clipboard write/read; used by `output/clipboard.py:ClipboardManager`.
- **pw-play** (preferred) / **paplay** (fallback) — audio cue playback subprocess; used by `audio/feedback.py:Feedback`. Volume: pw-play takes 0..1 float, paplay takes 0..65536 int (linear).
- **notify-send** — desktop notifications; used by `notification.py:DesktopNotification`. No-ops if absent; self-heals with cooldown on failure.
- **systemctl** (`--user`) — daemon lifecycle management (`enable`/`start`/`stop`/`disable` CLI subcommands; also used internally by `update.py` to stop/start the daemon around a self-update).

## System libraries (native, not bundled — required at runtime)
- **libportaudio** — PortAudio runtime backing `sounddevice`; PyInstaller hook (`packaging/rthooks/py_rth_portaudio.py`) injects `LD_LIBRARY_PATH` for the frozen binary to find it.
- **libevdev** — backs the `evdev` Python wheel.
- **libpipewire** / **libpulse** — audio infrastructure behind pw-play/paplay.

## Services
- **GitHub Releases** — self-update transport (`update.py`) and end-user binary distribution (`packaging/install.sh`); SHA-256 verified.
- **Hugging Face Hub** — ASR model hosting; default model repo `Systran/faster-distil-whisper-medium.en`.

## CI/CD tooling (`.github/workflows/`)
- **actions/checkout@v7**, **actions/setup-python@v6**, **softprops/action-gh-release@v3** — GitHub Actions building blocks for `release.yml`.
- **gh CLI** — used in `release-badge.yml` to query the latest release tag.

## Distro packaging (installer-time, not Python deps)
- `apt-get` / `dnf` / `pacman` detection in `packaging/install.sh` for installing system deps (libportaudio2, wtype, wl-clipboard, pipewire-audio, libevdev-dev, etc. per distro).
