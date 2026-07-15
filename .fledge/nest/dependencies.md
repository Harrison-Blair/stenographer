---
generated: 2026-07-15T17:38:33Z
commit: d621b46261d9509fccbdffc4686be0b876c7951e
agent: fledge-forager
fledge_version: 0.5.4
---

# Dependencies

External packages, system tools, libraries, and services stenographer relies on, deduplicated across build/runtime/test with usage notes.

## Python runtime dependencies (`pyproject.toml`)

- `sounddevice>=0.4.7` — PortAudio wrapper; mic capture (`audio/capture.py`), device enumeration for `capabilities.py`.
- `numpy>=2.0` — audio buffer arrays, RMS computation, resampling math.
- `faster-whisper>=1.0.0` — offline ASR engine, wrapped by `asr/model.py`.
- `evdev>=1.4` — Linux input-device API; hotkey listener reads `/dev/input/event*`.
- `soundfile>=0.12` — WAV I/O for cue playback assets and `transcribe FILE`/bench clip loading.
- `packaging>=24.0` — version comparison in self-update (`update.py`).
- `certifi>=2024.0` — TLS CA bundle for HTTPS calls to GitHub Releases.
- `huggingface_hub>=0.23` — ASR model download (`snapshot_download`, `try_to_load_from_cache`).
- `argcomplete>=3.5` — shell tab-completion; `_parser.py` is deliberately lightweight to keep this hot path fast.

## Python dev/build extras

- `ruff>=0.5` — lint + format (line-length 100, target py314, rules `E,F,I,B,UP,N,SIM,RUF`).
- `pytest>=8`, `pytest-asyncio>=0.23` — test runner and async test support.
- `pyinstaller>=6.10` — standalone binary build (`packaging/stenographer.spec`).

## Stdlib usage of note

- `tomllib` — config parsing (`config.py`), version extraction in `release.yml` (Python 3.11+ required).
- `fcntl.flock` — single-instance daemon lock, and an exclusive update lock in `update.py`.
- `ctypes` — `asr/worker.py` calls glibc `malloc_trim(0)` for arena cleanup after model unload (Linux/glibc only, no-op elsewhere).
- `weakref` — `LazyModel` → `Worker` back-reference for disposal without a cycle.
- `urllib`, `tarfile`, `hashlib`/SHA-256 — self-update download, extraction, and integrity verification.

## Required system CLIs (checked by `capabilities.py` / `doctor`, installed via `install.sh`)

- `wtype` — Wayland text injection at cursor (`output/inject.py`).
- `wl-copy` / `wl-paste` — Wayland clipboard write/read (`output/clipboard.py`).
- `pw-play` or `paplay` — audio feedback cue playback (`audio/feedback.py`); volume control differs (pw-play: 0..N float, paplay: 0..65536 int).
- `notify-send` — desktop notifications; degrades to no-op if absent (`notification.py`).
- `systemctl` — daemon lifecycle (`enable`/`start`/`stop`/`disable` subcommands, `--user` scope); optional, skipped if unavailable.
- `curl`/`wget`, `sha256sum`, `tar` — used by `install.sh` to fetch, verify, and unpack releases.

## Required system libraries (not bundled in the frozen binary)

- `libevdev1`/`libevdev-dev` — backs `python-evdev`; headers required at build time.
- `libportaudio2`/`portaudio` — backs `sounddevice`; resolved at runtime via `LD_LIBRARY_PATH` set by `packaging/rthooks/py_rth_portaudio.py`.
- `libGL`/Vulkan — required by `onnxruntime` for CPU inference (faster-whisper backend), per `src-audio.md`'s packaging notes.

## External services

- **GitHub Releases API** — self-update source (`update.py`) and distribution channel for prebuilt binaries (`.github/workflows/release.yml`, `install.sh`).
- **Hugging Face Hub** — ASR model distribution; default model `Systran/faster-distil-whisper-medium.en` (~800 MB, `config.py:168`), never bundled, fetched via `stenographer model download` → cached at `$XDG_CACHE_HOME/huggingface/hub/` (root.md, scripts.md). A second, larger model `Systran/faster-whisper-large-v3` is used as the benchmarking gold standard (`bench.py:_GOLD_MODEL`) and by ASR unit tests (`test_transcription.py`, `test_lazy_model.py`) — both models are listed as user-selectable choices in `cli.py:560-561`.
- **Local LLM endpoint (optional, prompt mode)** — `llm.py:rewrite_prompt()` sends transcripts to an OpenAI-compatible local endpoint (`LlmConfig.base_url`); all failures collapse to `LlmError` and fall back to raw transcript.

## GitHub Actions dependencies (`.github/workflows/`)

- `actions/checkout@v7`, `actions/setup-python@v6`, `softprops/action-gh-release@v3`.
- apt packages installed in CI: `libportaudio2`, `wtype`, `wl-clipboard`, `pipewire-audio`, `libevdev-dev`.

## Test-only dependencies

- `unittest.mock` (`MagicMock`, `patch`, `patch.dict`, `patch.object`) — mocking subprocess/HTTP/sounddevice/evdev.
- `pytest.MonkeyPatch`, `pytest.CaptureFixture` — env/attribute patching and stdout/stderr capture.

## Open Questions

- Are Wayland compositor/protocol versions pinned or tested against a specific set (wlroots, Hyprland, Sway, KWin, Mutter mentioned in docs but coverage unclear)? (`root.md`)
