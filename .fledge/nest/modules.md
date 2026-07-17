---
generated: 2026-07-17T01:39:59Z
commit: 939420f205b102d61ab3d7ed257a1680a61483dc
agent: fledge-forager
fledge_version: 0.5.8
---

# Modules

Repo map: every top-level module and `src/stenographer/` subpackage, its purpose, key files, and where to look for what.

## root (repo root files)

Project metadata and docs. `pyproject.toml` (hatchling; name `stenographer` v0.8.0; 9 runtime deps; ruff/pytest config), `.python-version` (3.14), `README.md` (user docs), `BUILD.md` (PyInstaller build), `AGENTS.md`/`CLAUDE.md` (dev guides), `LICENSE` (GPLv3-or-later).
Look here for: version/dependency source of truth, ruff/pytest config, top-level project docs.

## .github + .githooks (merged as `github`)

CI/CD and git hooks. `.github/workflows/ci.yml` (PR validation: lint+test+build, no publish), `release.yml` (push-to-main: lint+test+build+publish GitHub Release, enforces version bump via `gh release view`), `release-badge.yml` (post-release badge update on orphan `badges` branch). `.githooks/pre-commit` (ruff format on staged `.py` files).
Look here for: what CI checks run on a PR, how releases are published/versioned, pre-commit hook behavior.

## packaging

Standalone-binary packaging. `stenographer.spec` (PyInstaller spec, `--onedir`), `hook-sounddevice.py` + `rthooks/py_rth_portaudio.py` (PyInstaller hooks excluding/relinking native audio libs), `install.sh` (interactive release installer: deps, input group, binary download+verify, config, model, systemd), `stenographer.service.in` (systemd user unit template), `stenographer-completion.bash` (shell tab-completion).
Look here for: how the frozen binary is built/bundled, systemd unit template, release installer flow.

## scripts

Dev/build/setup automation, run from repo root. `build.sh` (PyInstaller wrapper → `dist/stenographer/stenographer`), `build-and-install.sh` (build.sh + install.sh), `install.sh` (source-tree install to `~/.local/share/stenographer/` + symlink + completion + systemd unit), `install-hooks.sh` (sets `core.hooksPath`), `download_model.py` (fetches ASR model via `huggingface_hub.snapshot_download`), `gen_cues.py` (generates the 11 WAV feedback cues under `src/stenographer/assets/sounds/` via numpy+soundfile).
Look here for: local dev setup commands, how the WAV feedback cues are generated/regenerated.

## src/stenographer/ (cross-cutting: `__init__.py`, `_parser.py`, `cli.py`, `config.py`, `capabilities.py`, `errors.py`, `notification.py`, `update.py`, `bench.py`, `assets/`)

Entry-point dispatch and cross-cutting infrastructure. `cli.py::main()` dispatches 13 subcommands (`run`, `dictate`, `transcribe`, `bench`, `model download`, `update`, `doctor`, `devices`, systemd `enable/disable/start/stop`) and builds the `Session` via `_build_session()`. `_parser.py` is a lightweight argparse builder kept separate for the argcomplete hot path. `config.py` defines the full frozen-dataclass config schema (`Config`, `HotkeyConfig`, `AudioConfig`, `AsrConfig`, `OutputConfig`, `ClipboardConfig`, `StreamingConfig`, `FormattingConfig`, `UpdateConfig`) and TOML loading/validation. `capabilities.py::Capabilities.probe()` checks wtype/wl-copy/pw-play/paplay/input-group/mic/ASR-model. `errors.py` defines the `StenographerError` hierarchy and `fatal`/`notify_failure`/`degrade_capability` helpers. `notification.py::DesktopNotification` wraps `notify-send` on a background thread. `update.py` implements self-update from GitHub Releases (SHA-256 verify, atomic onedir swap). `bench.py` is an ASR benchmarking harness (WER, RTF across model/beam/compute-type matrix). `assets/sounds/*.wav` (11 cues) and `assets/icons/stenographer.png` are bundled static assets.
Look here for: adding a CLI subcommand, changing/validating config schema (including `hotkey.trigger_mode`, `output.injection_method`), capability probing/doctor behavior, self-update logic, error-handling conventions.

## src/stenographer/session.py + live.py (module: `src-session-live`)

The orchestrator. `session.py::Session` is the single point of state transitions for one utterance (hotkey → record → transcribe → output), guarded by an `RLock`; routes each utterance into one of three pipelines (batch / paste-chunk-aggregation / streaming) — see `architecture.md`. `live.py::LiveStreamer` drives one streamed utterance: partials → coalesce → re-decode (`Worker.submit_words`) → `StreamingTranscriber` commit → `HeuristicFormatter` → typed delta, with a tail-silence guard (`_cut_trailing_silence`) against Whisper hallucination over quiet audio.
Look here for: recording lifecycle/cancellation semantics, how the three pipelines are chosen and wired, the live-typing invariant (typed text never revised), thread-safety/locking strategy across hotkey/recorder/worker callbacks.

## src/stenographer/hotkey/

Global hotkey detection. `binding.py::HotkeyBinding` parses/canonicalizes config binding strings (e.g. `"KEY_A+KEY_LEFTCTRL"`) against `evdev.ecodes.KEY`. `listener.py::HotkeyListener` is the daemon-threaded evdev read loop over `/dev/input/event*` (auto-detects multi-HID keyboards, handles device loss/reacquisition, stuck-key recovery). `state_machine.py::HotkeyStateMachine` is a **pure** (no I/O) 5-state FSM implementing the hybrid trigger (short press = toggle via double-tap window, ≥`threshold_seconds` (default 0.5s) = push-to-talk) or toggle-only mode (`trigger_mode` config: `"hybrid"` | `"toggle"`, no third value yet).
Look here for: hotkey binding syntax, PTT/toggle/hybrid trigger semantics, evdev device auto-detection and multi-keyboard handling — **primary module for the planned push-to-talk trigger-mode change**.

## src/stenographer/audio/

Mic capture and audio feedback. `capture.py::Recorder` captures via sounddevice/PortAudio with device-rate fallback cascade (48k→44.1k→22.05k→16k→8k, then channels 2→1) and polyphase-FIR resampling to the configured rate; supports RMS-based silence detection (`silence_rms_threshold`, default 0.01 — flagged in Open Questions as possibly too high for quiet mic input) with mid-recording flush, and a `snapshot()` API for live-streaming partial re-decodes. `feedback.py::Feedback` plays the 11 WAV cues via `pw-play` or `paplay` subprocess, with asset-override resolution.
Look here for: mic capture/resampling/silence-detection logic, audio feedback cue playback.

## src/stenographer/asr/

Speech recognition. `model.py::Model`/`LazyModel` wrap `faster-whisper`'s `WhisperModel` (`LazyModel` loads on first use, unloads after `idle_unload_seconds` idle, via a generation-token race guard). `worker.py::Worker` runs transcription off the main thread with cancellation support: `submit()` (batch job, `TranscriptionResult`) or `submit_words()` (word-timestamped re-decode, `list[WordInfo]`, used by live streaming). `streaming.py::StreamingTranscriber` is a **pure** LocalAgreement-N committer: a word is committed (and thus typed) only after N consecutive re-decode hypotheses agree on it, and committed words are never revised.
Look here for: ASR model lifecycle (lazy-load/idle-unload), transcription cancellation, the LocalAgreement-N streaming commit algorithm — **primary module for the planned text-streaming work**.

## src/stenographer/output/

Output delivery. `inject.py::Injector` types text at the cursor via `wtype` (`type_text()`) and can simulate Ctrl+V (`paste()`, already present) via `wtype -M ctrl v -m ctrl`; stateless, degrades to no-op when wtype is unavailable. `clipboard.py::ClipboardManager` wraps `wl-copy` (write) / `wl-paste` (read, test-only); populated independently as the fallback path when injection fails, and as the primary sink in paste mode. `formatter.py::HeuristicFormatter` is a stateful, append-only formatter (spacing, capitalisation, pause-based paragraph breaks) shared by both the batch and live-typing paths via a `_Token` protocol that accepts both `WordInfo` and `SegmentInfo`.
Look here for: how typed/pasted output is produced and formatted, wtype/wl-copy subprocess invocation patterns, the append-only formatting invariant — **primary module for the planned wtype→paste injection change** (the paste path already exists: `injection_method="paste"` + `Injector.paste()`).

## tests

Mirrors `src/stenographer/` 1:1 (26 files). pytest-based; unit tests run via `pytest -m "not integration"`, the 4 `@pytest.mark.integration`-marked tests (real audio, real wtype, real wl-copy round-trip, real pw-play) require `STENOGRAPHER_INTEGRATION=1` and skip if the underlying tool/display is unavailable. ~360+ test functions total (see `testing.md`).
Look here for: how to run/write tests for a given module, integration-test gating pattern, existing coverage before changing a component's behavior.
