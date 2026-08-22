# AGENTS.md

Guidance for AI agents (and humans) working in this repository. This is the
single canonical file; `CLAUDE.md` imports it and adds nothing. When this file
and `docs/reauthor.md` disagree, `docs/reauthor.md` wins — it is the design
record: its §2 decisions are settled, its §4 behavioral knowledge inventory
binds every change, §6 is the testing policy, §7 lists deliberately cut
features.

## What this is

`stenographer` is a local-only push-to-talk dictation daemon. Hold a global
hotkey, speak, release: the recognized text is copied to the clipboard and
pasted at the cursor with a synthesized paste chord. `hotkey.mode = "toggle"`
presses once to start and again to stop. Offline, English-only,
GPL-3.0-or-later, Python ≥ 3.12.

**Target platforms: Linux (Wayland, any compositor) and Windows.** Linux is
the shipping backend; Windows currently has a stdlib-only stub provider and a
CI portability job, with the real backend tracked in `docs/reauthor.md` §7.
Every change must keep both targets viable — see *Platform boundary* below.

Do not reintroduce cut features (old HUD / transcript preview, hybrid trigger
mode, self-update, sound downloads, per-cue overrides, multi-distro installers)
without revising `docs/reauthor.md` first. Already authorized: toggle mode, the
isolated lifecycle pill (exactly 18 locally analyzed spectrum bars while
recording, a helper-local amber border pulse only while the model loads, fixed
state interiors — never transcript preview, controls, GTK, or raw-audio IPC),
the local PyInstaller onedir build + per-user installer + `main`-only draft
release workflow, and static Bash/Zsh/Fish completions.

## Commands

All Python tooling runs through the repo venv (`.venv/`, gitignored). **Never
use the system `python` / `pip` / `ruff` / `pytest`.**

```sh
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"   # recreate venv
.venv/bin/ruff check . && .venv/bin/ruff format --check .    # lint (--fix to autofix)
.venv/bin/pytest -m "not integration"                        # unit suite
STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest                  # + smoke (real machine only)
.venv/bin/pytest tests/test_daemon.py::test_name             # single test
.venv/bin/stenographer --help                                # CLI smoke
```

Quick verification loop before every commit: ruff check + format, unit suite,
`--help`. `integration`-marked tests touch the real clipboard / audio / uinput
/ model and need a real machine — never set `STENOGRAPHER_INTEGRATION` in CI
or sandboxes. CI runs the unit suite on `ubuntu-latest` and `windows-latest`
(`unit-windows`: install, pure suites, `--help`; `tests/platform/linux/` is not
collected there).

## Platform boundary (binding)

OS- and desktop-specific code is **fully disconnected** from business logic.
The rule is structural, not stylistic, and it is enforced by a test.

- **Where host code lives.** `src/stenographer/platform/` is the *only* place
  OS/desktop-specific code may exist. `platform/base.py` is stdlib-only and
  defines the contract as `typing.Protocol`s: `Platform`, `KeyTable`,
  `HotkeyListener`, `KeyInjector`, `ClipboardWriter`, `Notifier`, `CuePlayer`,
  `SingleInstanceLock`, `OverlayBackendSpec`, `HostProbe`, plus
  `UnsupportedPlatformError`, `SingleInstanceLockError`, `NullNotifier`.
  `platform/linux/` is `LinuxPlatform` (XDG dirs, child env, flock, evdev
  hotkeys + binding capture, uinput Shift+Insert, wl-copy/xclip, notify-send,
  canberra/pw-play/paplay cues, doctor probes + systemctl, layer-shell→XWayland
  overlay specs). `platform/windows/` is `WindowsPlatform`: today a stub that
  imports everywhere and reports every surface unavailable (`doctor` exits 78,
  `run` is refused); it will grow `WH_KEYBOARD_LL`, `SendInput`, Win32
  clipboard, toast, cue player, named mutex, `SetConsoleCtrlHandler`.
- **How the core reaches it.** Everything else — `daemon`, `hotkey`, `audio`,
  `config`, `status`, `cli/`, `transcribe/`, `overlay/` (daemon side),
  `delivery/`, `utils/` — is *core* and talks to the host only through
  `from stenographer.platform import current_platform` (a cached
  `sys.platform` switch) or an injected Protocol instance.
  `Daemon.build(cfg, platform=)` is the single wiring point. Core never
  imports `stenographer.platform.linux`, `stenographer.platform.windows`,
  `evdev`, `fcntl`, `termios`, `grp`, `pty`, `pywayland`, `Xlib`, or any
  Win32 module — not even lazily inside a function. `tests/platform/
  test_core_isolation.py` imports every core module in a fresh interpreter
  with those names blocked; a violation anywhere in the core fails it.
- **Provider modules are lazy.** Each `LinuxPlatform` / `WindowsPlatform`
  method lazy-imports its sibling backend so `stenographer --help` never
  loads evdev or pywin32; `platform/__init__.py` and both provider
  `__init__.py` files must stay importable on every OS (the Linux bundle
  `collect_submodules` the Windows stub too). OS-only third-party deps carry
  `sys_platform` markers in `pyproject.toml`.
- **Shared vocabulary is core data, not a host capability.** `hotkey.binding`
  uses evdev `KEY_*` names on every platform; `keycodes.py` (generated, pure)
  holds the table so a Windows provider maps names → VK codes without a schema
  change. `status.Backend` is protocol-v4 wire vocabulary; a Windows overlay
  backend is a protocol-extension decision, and until then the overlay is
  disabled there. `doctor.REQUIRED` field names are semantic (injector
  available, listener permitted, clipboard available, mic, model) — the
  startup gate needs no renaming per OS; only labels and fix hints differ.
- **How to add or change host behaviour.** (1) If it is a new capability,
  add a Protocol method/type to `platform/base.py` with a stdlib-only
  signature. (2) Implement it in `platform/linux/`, and in
  `platform/windows/` either implement it or make the stub report it
  unavailable / raise `UnsupportedPlatformError` — the stub must still import
  and every `Platform` method must still exist. (3) Wire it into the core via
  `current_platform()` or `Daemon.build`. (4) Keep the core's pure part
  testable without any OS: if you find yourself wanting to mock a subprocess,
  device, or OS call, the host part has leaked into the core — move it behind
  the Protocol instead. (5) Paths, env lookup (`XDG_*`, `%APPDATA%`,
  `%LOCALAPPDATA%`), process/child env, signals vs console handlers, locks,
  service control, and notifications are all host concerns; never hardcode a
  Linux assumption (`/dev/uinput`, `/tmp`, `os.getuid`, `fcntl`, `SIGTERM`
  semantics, `systemctl`, `/` separators) in core code.
- **Tests follow the same line.** `tests/platform/linux/` holds Linux-only
  tests (skipped/ignored off-Linux); pure overlay backend tests `importorskip`
  pywayland/Xlib. New core tests must pass on `windows-latest` with no Linux
  backend present.

## Hard rules

1. **Venv only** — `.venv/bin/...` for everything.
2. **Python 3.12 compatibility** — ruff targets py312; no 3.13+/3.14-only
   syntax. ruff: line length 100, rules `E,F,I,B,UP,N,SIM,RUF`.
3. **SPDX header** `SPDX-License-Identifier: GPL-3.0-or-later` on every
   source file. `pyproject.toml` (hatchling) is the single source of truth
   for metadata/deps.
4. **Testing policy is binding** (docs/reauthor.md §6): unit tests for pure
   logic only (formatter, config validation, gate math, protocol
   encode/decode, parser); never mock `subprocess` / `UInput` / `wl-copy` /
   Win32 to assert a call would have happened; mock-only testability is a
   design smell — extract the pure part; a new pure-logic test only counts
   once it has been SEEN to fail against broken behavior; the integration
   smoke suite (genuinely creates a uinput device, writes the clipboard, plays
   cues, loads the model) is the real gate and must be green on a real machine
   before any dev → main merge.
5. **Behavioral invariants** (docs/reauthor.md §4) most at risk in edits:
   never gate audio on absolute RMS defaults (quiet-mic rule — two consecutive
   50 ms frames); the paste chord fires only after a *confirmed* clipboard
   copy AND physical hotkey release — a failed copy never fires the chord; the
   daemon never touches the network (`local_files_only`); the PortAudio
   callback only copies blocks (no analysis); one utterance at a time; capture
   starts before the `record_start` cue and stops/secures samples before
   `record_stop`.
6. **Privacy in logs** — numeric/structural metrics and transcript *lengths*
   only; never transcript text, audio, samples, or result representations.
7. **Overlay isolation** — the optional helper receives only fixed lifecycle
   metadata, a model-loading boolean, and 18 quantized spectrum levels over
   the versioned NDJSON protocol (v4); pulse timing is helper-local; raw
   samples stay in the daemon-side supervisor; the helper is click-through and
   failure-disabled. Never run analysis/display/process I/O under daemon
   locks; never send transcript, raw audio, device/model names, config values,
   or detailed errors across IPC.
8. **Sound-pack boundary** — selection is global and whole-pack only. Bundled
   packs: `legacy`, `warm-desk`, `soft-electronic`, `minimal-ui` (reserved
   names, win collisions, listed only when complete). Custom packs live under
   `<active-config-directory>/sounds/<pack>/`, local-only, and must pass the
   four-cue WAV validation; invalid selection warns once and falls back to
   `minimal-ui`. Static completions expose only the four bundled names.
9. **Config is fixed** — exactly 20 keys in 4 sections (`hotkey`, `audio`,
   `asr`, `feedback`), frozen dataclasses, key-scoped `ConfigError` → exit 78,
   no migrations, no setup-only keys. Setup/sounds save through the tomlkit
   preservation layer (comments, ordering, unknown content, symlinks, mode;
   timestamped backup; unchanged bytes not written).
10. **Branch model** — develop on `dev`; merge to `main` only after the smoke
    suite and real dictation pass on a real machine. Commits are conventional
    (`feat:`, `fix:`, `chore:`) with no attribution trailers.

## Architecture map

`src/stenographer/` (src-layout); `tests/` mirrors the grouping. Behavioral
detail for every item below (exit codes, calibration math, menu semantics,
cue ordering) lives in `docs/reauthor.md` §4 — do not re-derive it from code.

| Module | Role |
|---|---|
| `daemon.py` | Orchestrator: hotkey → record → transcribe → deliver. `Daemon.build(cfg, clipboard_backend=, status=, platform=)`; `run()` takes the platform single-instance lock, installs stop handlers, prepares audio, starts the listener. Warms a cold model in the background once capture starts; toggle mode ends at `audio.max_recording_seconds` through the same stop path. |
| `hotkey.py` | Platform-neutral `parse_binding` (via `KeyTable`), `chord_active`/`edge`, `ChordTracker` (held-key union across devices, stuck-key synthesis, `wait_binding_released`). Providers subclass it and feed `_key_event(device_id, code, value)`. |
| `keycodes.py` | Generated pure `KEY_*`/`BTN_*` name→code table (`scripts/gen_keycodes.py`); drift test on Linux. |
| `audio.py` | PortAudio recorder: retained pre-negotiated stream, block-copy callback with latest-only handoff to the overlay supervisor, RMS speech gate, sample-rate fallback + resample, one stale-stream recovery. |
| `config.py` | TOML → frozen dataclasses; missing file written with annotated defaults; in-memory load path for validating setup output. |
| `status.py` | Lifecycle states + strict protocol-v4 NDJSON contract + pure generation/coalescing policy. |
| `transcribe/` | `worker.py` (crash-isolated ASR child: one job at a time, load-only warm-up, idle unload after `asr.idle_unload_seconds`, logs via queue), `model.py` (faster-whisper, anti-hallucination stack, `PathologicalOutputError`, `local_files_only`), `format.py` (zero-knob formatter). |
| `delivery/` | `deliver.py` (`Deliverer` policy: confirmed copy → wait for release → `KeyInjector` chord), `feedback.py` (resolve one sound pack at startup, mute/volume policy, `CuePlayer`; no player → no-op). |
| `overlay/` | `spectrum.py` (pure 32 ms Hann FFT, 18 bands, fixed floors, 18-level quantization), `supervisor.py` (helper spawn/mailbox/backend selection), `render.py`, `wayland.py` / `x11.py` helper backends reached only via `overlay_backends()`, vendored `protocols/`. |
| `cli/` | argparse surface + lazy dispatch (`stenographer.cli:main`; `python -m stenographer.cli` for helper re-exec); `commands/` thin handlers for `run`, `transcribe`, `model download`, `doctor`, `devices`, `setup`, `sounds`, `completion {bash,zsh,fish}`. Heavy imports stay inside handlers. Engines: `setup.py` (TTY-only full / `--quick`), `setup_config.py` (preservation layer), `binding_capture.py` (pure reducer + `current_platform().capture_binding`), `calibration.py` (one-shot 18-band floor estimator for `feedback.spectrum_floor_dbfs` only), `doctor.py` (`REQUIRED` gate → exit 78; host half from `probe_host()`), `sounds.py`. Completion is static — no device/model/config/audio/network discovery. |
| `platform/` | The host boundary — see above. |
| `utils/logging_setup.py` | Idempotent stderr + rotating state-file logging (5 MiB × 3), `STENOGRAPHER_LOG_LEVEL`, privacy-safe worker forwarding. |
| `assets/` | Sound packs (`sounds/<pack>/`), icon, font, static completions. |
| `packaging/`, `scripts/` | systemd user unit; `build.sh` / `install.sh` (local bundle, per-user install), `gen_keycodes.py`, `cue_audition.py`, `sound_asset_guard.py`. |
| `docs/` | `reauthor.md` (design record), `code-smells.md` / `refactoring-techniques.md` (review/refactor references), `cue-audition.md`. |

The ASR model (~1.5 GB) is never bundled — `stenographer model download`
fetches it once; `asr.hotwords` require a full (non-distil) model.
