# AGENTS.md

Guidance for AI agents (and humans) working in this repository. This is the
single canonical file — the design record as well as the working guide.
`CLAUDE.md` imports it and adds nothing. Settled decisions live here; changing
one means editing this file in the same commit as the code that changes it.

## What this is

`stenographer` is a local-only push-to-talk dictation daemon. Hold a global
hotkey, speak, release: the recognized text is copied to the clipboard and
pasted at the cursor with a synthesized paste chord. `hotkey.mode = "toggle"`
presses once to start and again to stop. Offline, English-only,
GPL-3.0-or-later, Python ≥ 3.12.

**Target platforms: Linux (Wayland, any compositor) and Windows.** Linux is
the shipping backend; Windows currently has a stdlib-only stub provider and a
CI portability job, with the real backend scoped in `docs/windows/SCOPE.md`.
Every change must keep both targets viable — see *Platform boundary* below.

Do not reintroduce cut features (old GTK HUD / transcript preview, hybrid
trigger mode, cancel binding, `dictate`, `bench`, per-character typing / wtype,
live preview / incremental decoding, self-update, sound downloads, per-cue
overrides, config migrations, multi-distro installers) without recording the
decision in this file first. Already authorized: toggle mode, the isolated
lifecycle pill (exactly 18 locally analyzed spectrum bars while recording, a
helper-local amber border pulse only while the model loads, fixed state
interiors — never transcript preview, controls, GTK, or raw-audio IPC), the
local PyInstaller onedir build + per-user installer + `main`-only draft
release workflow (with a read-only release-preflight rehearsal — version/tag
guard plus wheel/sdist verification — on PRs into `main`), the curl-piped
`scripts/quick-install.sh` bootstrap (installs the latest *published*
release's native bundle by handing it to that release's own sdist
`install.sh` after `SHA256SUMS` verification — an install path, never
self-update), the daemon-start update *notice* (at most one metadata-only
HTTPS request per 24 h for the latest published GitHub release tag, a desktop
notification pointing at the README quick-install command, opt out with
`feedback.update_check = false` — it never downloads and never updates
anything), the queue-backed logging pipeline (one listener thread owning the
stderr sink and the always-DEBUG rotating file, `subsystem: event key=value`
lines, `utt=N` correlation, `feedback.log_level`, and a helper-local
`overlay-helper.log`), and static Bash/Zsh/Fish completions.

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

`feedback.log_level` sets the stderr/journal threshold; `STENOGRAPHER_LOG_LEVEL`
overrides it for a single process (it is resolved before any config is read, so
it also wins over the daemon's re-apply). `stenographer.log` keeps DEBUG either
way.

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
  OS/desktop-specific code may exist — with no exceptions left: the overlay
  helper's layer-shell and XWayland backends live under
  `platform/linux/overlay_backends/` too. `platform/base.py` is stdlib-only and
  defines the contract as `typing.Protocol`s: `Platform`, `KeyTable`,
  `HotkeyListener`, `KeyInjector`, `ClipboardWriter`, `Notifier`, `CuePlayer`,
  `SingleInstanceLock`, `HelperTransport` / `HelperProcess`,
  `OverlayBackendSpec`, `HostProbe`, `HostGuidance`, plus
  `UnsupportedPlatformError`, `SingleInstanceLockError`, `NullNotifier`.
  `platform/linux/` is `LinuxPlatform` (XDG dirs, child env, flock, evdev
  hotkeys + binding capture, uinput Shift+Insert, wl-copy/xclip, notify-send,
  canberra/pw-play/paplay cues, sysfs CPU topology, doctor probes + systemctl,
  the overlay helper's pipes/`select`/SIGTERM→SIGKILL transport in
  `linux/helper.py`, the layer-shell→XWayland overlay specs in `linux/overlay.py`
  plus the helper-side backends and vendored Wayland protocol bindings they
  construct in `linux/overlay_backends/` (whose `base.py` holds everything the
  two backends share — `BackendUnavailableError`, `probe_backend`, the selector
  loop with its hooks, the loading-frame timer, the frame request, idempotent
  `close()` — so a backend module is only its own display primitives), and every
  Linux word the CLI prints in `linux/guidance.py`).
  `platform/windows/` is `WindowsPlatform`: today a stub that
  imports everywhere and reports every surface unavailable (`doctor` exits 78,
  `run` is refused); it will grow `WH_KEYBOARD_LL`, `SendInput`, Win32
  clipboard, toast, cue player, named mutex, `SetConsoleCtrlHandler`.
- **How the core reaches it.** Everything else — `daemon`, `hotkey`, `audio`,
  `audio_probe`, `capabilities`, `config`, `status`, `cli/`, `transcribe/`,
  `overlay/` (daemon side), `delivery/`, `utils/` — is *core* and talks to
  the host only through
  `from stenographer.platform import current_platform` (a cached
  `sys.platform` switch) or an injected Protocol instance.
  `Daemon.build(cfg, platform=)` is the single wiring point. Core never
  imports `stenographer.platform.linux`, `stenographer.platform.windows`,
  `evdev`, `fcntl`, `termios`, `grp`, `pty`, `pywayland`, `Xlib`, or any
  Win32 module — not even lazily inside a function. `tests/platform/
  test_core_isolation.py` imports every core module in a fresh interpreter
  with those names blocked; a violation anywhere in the core fails it. Some
  stdlib modules import fine everywhere and only *behave* per-OS — a core
  driver (`overlay/supervisor.py`, `audio.py`, `hotkey.py`, `daemon.py`)
  therefore never reaches for `subprocess`, `selectors`, `fcntl`, `signal`,
  `msvcrt`, or raw `os.read`/`os.kill` either; the same test greps their
  source for it.
- **Provider modules are lazy.** Each `LinuxPlatform` / `WindowsPlatform`
  method lazy-imports its sibling backend so `stenographer --help` never
  loads evdev or pywin32; `platform/__init__.py`, both provider
  `__init__.py` files, and `linux/overlay_backends/__init__.py` must stay
  stdlib-only and importable on every OS (the Linux bundle
  `collect_submodules` the Windows stub too). OS-only third-party deps carry
  `sys_platform` markers in `pyproject.toml`.
- **Shared vocabulary is core data, not a host capability.** `hotkey.binding`
  uses evdev `KEY_*` names on every platform; `keycodes.py` (generated, pure)
  holds the table so a Windows provider maps names → VK codes without a schema
  change. `status.Backend` is protocol-v4 wire vocabulary; a Windows overlay
  backend is a protocol-extension decision, and until then the overlay is
  disabled there. `capabilities.Capabilities` / `REQUIRED` field names are
  semantic and identical to `platform/base.HostProbe`'s (`key_injector_ok`,
  `hotkey_access_ok`, `has_mic`, `model_cached`, `clipboard_ok`) — the shared
  daemon/`doctor` startup gate needs no renaming per OS. Prose, however, is
  *not* shared vocabulary: the capability labels and fix hints keyed by those
  same names, the clipboard hints keyed by backend, the service noun /
  installer / unknown-state detail / start / restart / log-follow commands,
  the `hotkey.device` comment in the default config template, and the shell
  syntax for "run against this config path" all come from
  `platform/base.HostGuidance` via `current_platform().guidance()`.
  `cli/doctor.py`, `cli/setup.py`, `cli/sounds.py`, `cli/console.py`, and
  `config.py` own the
  sentence frames only — `systemctl`, `journalctl`, `install.sh`,
  `/dev/uinput`, `usermod`, `wl-clipboard`, and `xclip` must appear nowhere
  under `src/stenographer/` outside `platform/linux/`. Signal *names* are host
  prose too: `install_stop_handlers(handler)` calls back with a ready-made
  reason string (`"SIGTERM"`, later `"CTRL_CLOSE"`), formatted by the provider
  inside stop context — allocation-light and exception-safe, because the stop
  must fire even when the code cannot be named.
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
  service control, notifications, and machine introspection (CPU affinity and
  topology → `physical_core_count()`) are all host concerns; never hardcode a
  Linux assumption (`/dev/uinput`, `/tmp`, `/sys`, `os.getuid`,
  `os.sched_getaffinity`, `fcntl`, `SIGTERM` semantics, `systemctl`, `/`
  separators) in core code.
- **Tests follow the same line.** `tests/platform/linux/` holds Linux-only
  tests (skipped/ignored off-Linux), including the overlay backend tests; the
  ones that touch a backend module additionally `importorskip` pywayland/Xlib,
  while the shared `overlay_backends/base.py` tests need neither.
  `tests/overlay/` keeps only the shared pure ones (spectrum, render, reducer,
  supervisor, protocol). New core tests must pass on `windows-latest` with no
  Linux backend present.

## Hard rules

1. **Venv only** — `.venv/bin/...` for everything.
2. **Python 3.12 compatibility** — ruff targets py312; no 3.13+/3.14-only
   syntax. ruff: line length 100, rules `E,F,I,B,UP,N,SIM,RUF`.
3. **SPDX header** `SPDX-License-Identifier: GPL-3.0-or-later` on every
   source file. `pyproject.toml` (hatchling) is the single source of truth
   for metadata/deps.
4. **Testing policy is binding.** Unit tests cover pure logic only —
   formatter, config validation, gate/spectrum/calibration math, protocol
   encode/decode and ordering, renderer geometry, chord parsing, capture
   reducers, TOML transformation. Never mock `subprocess` / `UInput` /
   `wl-copy` / Win32 to assert a call would have happened: a green mock proves
   nothing (489 mocked tests once stayed green for a year while paste was
   dead). Mock-only testability is a design smell — extract the pure part
   instead of writing the mock. A new pure-logic test only counts once it has
   been SEEN to fail against broken behavior. The integration smoke suite
   (genuinely creates a uinput device, writes and reads back the clipboard,
   plays every bundled pack, loads the model) is the real gate. Keep the
   test:src ratio near 1:1 — beyond that, tests are re-testing the same logic
   through different layers.
5. **Behavioral invariants** — binding on every change:
   - Never gate audio on absolute RMS defaults (quiet mics fall below
     "normal" thresholds); the speech gate requires two consecutive 50 ms
     frames above `audio.min_speech_rms`, and `0` disables it.
   - The paste chord fires only after a *confirmed* clipboard copy AND
     physical hotkey release. A failed copy never fires the chord (it would
     paste stale clipboard content); a still-held modifier would mutate the
     chord, so delivery waits for release and, on wait timeout, proceeds —
     the clipboard already holds the transcript as recovery.
   - An empty transcript or failed speech gate is success-shaped: no paste,
     no error cue.
   - The ASR path never touches the network (`local_files_only`), and
     `stenographer model download` is the only command that may download
     anything. The daemon's sole other network access is the update notice's
     single metadata request: a background daemon thread that is never joined,
     off the hot path, 5 s timeout, at most one request per 24 h, successful or
     not, via the record in the state directory, every failure DEBUG-logged and
     otherwise silent, disabled by `feedback.update_check = false`, and sending
     nothing but the request itself.
   - The PortAudio callback only copies blocks (no analysis, allocation-heavy
     work, or slow-consumer locks).
   - One utterance at a time; a start press during transcription neither
     starts nor queues.
   - Capture starts before the `record_start` cue and stops/secures samples
     before `record_stop`; cue failures cannot delay capture boundaries or
     orphan a recording.
   - Model load is press-lazy (starts on the first accepted recording, never
     at daemon startup) and intentionally silent so no cue contaminates
     captured audio. The anti-hallucination decode stack (VAD pre-filter,
     no-speech gate, silence trimming, short-audio token ceiling, output
     validation) is fixed behavior, not configuration.
   - `asr.cpu_threads = 0` means the host's `physical_core_count()` capped at
     8 — CTranslate2 scales badly past that and hyperthread counting is
     slower. A host that cannot count physical cores returns `None` and the
     thread count falls back to 4; never substitute a logical-CPU count.
   - `asr.hotwords` silently deletes words on distil models; hotword support
     requires a full model (why the default is `faster-whisper-medium.en`).
6. **Privacy in logs** — numeric/structural metrics and transcript *lengths*
   only; never transcript text, audio, samples, or result representations.
   Every line is `subsystem: event key=value ...` (`fmt_event`; a test parses
   every template under `src/`), and the rotating `stenographer.log` sink is
   unconditionally DEBUG — only the stderr/journal threshold is tunable, so a
   report never depends on a threshold set before the failure. Exceptions are
   logged through `log_failure(log, level, event, exc, *, safe=)`: `safe=True`
   renders `str(exc)` at *level* and the full traceback at DEBUG; `safe=False`
   renders the class name and `traceback.format_tb` frames only — the message
   is never formatted at any level. The text-capable lineages are the ASR
   child's `classify_error` inference branch (its detail becomes the
   `WorkerError` text) and the xclip clipboard read-back; neither may log a
   `CalledProcessError`'s `.output` or `.args`. The overlay helper writes its
   own `overlay-helper.log` in the state directory rather than sharing the
   daemon's file — nothing new crosses the IPC boundary to get there.
7. **Overlay isolation** — the optional helper receives only fixed lifecycle
   metadata, a model-loading boolean, and 18 quantized spectrum levels over
   the versioned NDJSON protocol (v4); pulse timing is helper-local; raw
   samples stay in the daemon-side supervisor; the helper is click-through and
   failure-disabled. Never run analysis/display/process I/O under daemon
   locks; never send transcript, raw audio, device/model names, config values,
   or detailed errors across IPC. The helper decides *nothing* about the
   lifecycle: `overlay/reducer.py` (core, pure, clock-injected) folds one
   accepted record into a redraw/teardown/stop intent for every backend, and
   the daemon-side supervisor is the **single authority** for the fixed 2.5 s
   error auto-hide — it queues the guarded hide (`status.error_timeout_applies`)
   like any other state. A backend must never run its own error timer: a
   supervisor that has stopped sends no further states *and* closes the
   helper's stdin, which ends the helper anyway.
8. **Sound-pack boundary** — selection is global and whole-pack only. Bundled
   packs: `legacy`, `warm-desk`, `soft-electronic`, `minimal-ui` (reserved
   names, win collisions, listed only when complete). Custom packs live under
   `<active-config-directory>/sounds/<pack>/`, local-only, and must pass the
   four-cue WAV validation; invalid selection warns once and falls back to
   `minimal-ui`. Static completions expose only the four bundled names.
9. **Config is fixed** — exactly 22 keys in 4 sections (`hotkey`, `audio`,
   `asr`, `feedback`), frozen dataclasses, key-scoped `ConfigError` → exit 78,
   no migrations, no setup-only keys. Setup/sounds save through the tomlkit
   preservation layer (comments, ordering, unknown content, symlinks, mode;
   timestamped backup; unchanged bytes not written).
10. **Branch model** — develop on `dev`; merge to `main` only after the
    acceptance gates below pass on a real machine. Commits are conventional
    (`feat:`, `fix:`, `chore:`) with no attribution trailers.

## Acceptance gates (real machine, before dev → main)

- `STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest` green.
- Real dictation end-to-end in both `hold` and `toggle` modes.
- After overlay-affecting changes: the pill appears on recording start and
  disappears on stop, the amber border breathes only during a cold load, and
  killing the helper never affects dictation.
- After capture/logging-affecting changes: a cold-start dictation retains its
  opening words, and an inspection of `stenographer.log` + the journal shows
  metrics but no transcript or audio content.
- After update-notice changes: a build whose `_version.py` is temporarily
  lowered pops the notification on daemon start with dictation unaffected, and
  `feedback.update_check = false` makes no request at all.

## Architecture map

`src/stenographer/` (src-layout); `tests/` mirrors the grouping. Behavioral
detail for every item below (exit codes, calibration math, menu semantics,
cue ordering) lives in the module docstrings and their tests — keep those
authoritative when editing.

| Module | Role |
|---|---|
| `daemon.py` | Orchestrator: hotkey → record → transcribe → deliver. `Daemon.build(cfg, clipboard_backend=, status=, platform=)`; `run()` takes the platform single-instance lock, installs stop handlers, prepares audio, starts the listener, and — when `feedback.update_check` is on — starts the update-notice thread. Warms a cold model in the background once capture starts; toggle mode ends at `audio.max_recording_seconds` through the same stop path. |
| `hotkey.py` | Platform-neutral `parse_binding` (via `KeyTable`), `chord_active`/`edge`, `ChordTracker` (held-key union across devices, stuck-key synthesis, `wait_binding_released`). Providers subclass it and feed `_key_event(device_id, code, value)`. |
| `keycodes.py` | Generated pure `KEY_*`/`BTN_*` name→code table (`scripts/gen_keycodes.py`); drift test on Linux. |
| `binding_capture.py` | Core capture vocabulary shared by `cli/` and every provider: `BindingCaptureError`, `CaptureState`, `KeyEvent`, pure `reduce_capture`, `serialize_capture` (validated canonical `KEY_*` names). No host imports. |
| `capabilities.py` | The shared capability gate (core, so the daemon never imports `cli/`): `Capabilities` / `OverlayCapability` with names identical to `HostProbe`'s, `REQUIRED`, pure `missing_required` (→ exit 78 / startup refusal), and the read-only `probe` / `probe_overlay` (host half from `probe_host()`, plus mic and model cache). Labels, fix hints, and rendering live in `cli/doctor.py`. |
| `audio_probe.py` | The one PortAudio input-device enumeration (`query_devices`, never raises) plus its pure adapters, shared by the capability gate, `setup`, and `devices`. |
| `update_check.py` | The daemon-start update notice (core, stdlib-only apart from an optional `certifi` CA bundle): pure `evaluate` (installed vs. latest tag, 1 h re-notify floor, never notifies for a local build ahead of the release), pure `build_request` and `tag_from_location` (the redirect target must sit under the repository's `releases/tag/` prefix, and the message renders from the parsed tag, never the URL), the cached record, and the thin edge — `fetch_latest_tag` (one metadata-only `HEAD` for the latest GitHub release, `User-Agent: stenographer-update-check`), `start_background_check`, and `run_check` (stamps the 24 h window on every attempt, fetches only when it has lapsed), which notifies through the platform `Notifier.info`. |
| `audio.py` | PortAudio recorder: retained pre-negotiated stream, block-copy callback with latest-only handoff to the overlay supervisor, RMS speech gate, sample-rate fallback + resample, one stale-stream recovery. |
| `config.py` | TOML → frozen dataclasses; missing file written with annotated defaults (`default_toml()` renders the template at write time so the `hotkey.device` comment comes from `HostGuidance`); in-memory load path for validating setup output. |
| `status.py` | Lifecycle states + strict protocol-v4 NDJSON contract + pure generation/coalescing policy. |
| `transcribe/` | `worker.py` (crash-isolated ASR child: one job at a time, load-only warm-up, idle unload after `asr.idle_unload_seconds`, fixed load/decode deadlines, logs via queue), `model.py` (faster-whisper, anti-hallucination stack, `PathologicalOutputError`, `local_files_only`), `format.py` (zero-knob formatter). |
| `delivery/` | `deliver.py` (`Deliverer` policy: confirmed copy → wait for release → `KeyInjector` chord), `feedback.py` (resolve one sound pack at startup, mute/volume policy, `CuePlayer`; no player → no-op). |
| `overlay/` | Core-side only: `spectrum.py` (pure 32 ms Hann FFT, 18 bands, fixed floors, 18-level quantization), `supervisor.py` (mailbox, NDJSON framing, readiness deadline, restart budget, the 2.5 s error auto-hide, and shutdown policy — the child itself is spawned, polled, read, and killed through `HelperTransport` / `HelperProcess`), `reducer.py` (the pure message→intent state machine every helper backend runs: command rejection, loading-edge dedupe, spectrum apply, state transitions with the recording level reset, teardown and pulse re-arm decisions), `render.py` (pure Pillow frame plus both placement policies, `overlay_position` / `layer_margin_bottom`), `entry.py`. The OS-specific helper backends live in `platform/linux/overlay_backends/` (shared `base.py`, `wayland.py` / `x11.py`, vendored `protocols/`) and are reached only via `overlay_backends()`. |
| `cli/` | argparse surface + lazy dispatch (`stenographer.cli:main`; `python -m stenographer.cli` for helper re-exec); `commands/` thin handlers for `run`, `transcribe`, `model download`, `doctor`, `devices`, `setup`, `sounds`, `completion {bash,zsh,fish}`. Heavy imports stay inside handlers. Engines: `console.py` (the shared interactive frame both `setup` and `sounds` build on: `Console`, stream defaulting, the TTY gate, the config-document load ladder, save reporting, yes/no and service-restart prompts), `setup.py` (TTY-only full / `--quick`), `setup_config.py` (preservation layer), `binding_capture.py` (thin `current_platform().capture_binding` delegator; the pure reducer is core `stenographer.binding_capture`), `calibration.py` (one-shot 18-band floor estimator for `feedback.spectrum_floor_dbfs` only), `doctor.py` (report layout: pure `render`/`format_service_status` taking a `HostGuidance`, plus `run`; the gate itself is core `stenographer.capabilities` and every host word is the platform's), `sounds.py`. Completion is static — no device/model/config/audio/network discovery. |
| `platform/` | The host boundary — see above. |
| `utils/logging_setup.py` | The logging pipeline: a `QueueHandler` on the `stenographer` logger and one `QueueListener` thread owning both sinks — stderr (threshold from `STENOGRAPHER_LOG_LEVEL`, else `feedback.log_level` re-applied by `run` through `apply_stderr_level`; no `asctime` when `Platform.journal_attached`) and the unconditionally DEBUG rotating state file (5 MiB × 3). Pure `fmt_event` / `stderr_format`, the `utt=N` filter (`set_utterance`), tiered `log_failure`, privacy-safe worker forwarding (the child's listener targets these same sinks via `owned_handlers()`), and a `shutdown_logging` that stops the listener so the tail is never lost. |
| `assets/` | Sound packs (`sounds/<pack>/`), icon, font, static completions. |
| `packaging/`, `scripts/` | systemd user unit; `build.sh` / `install.sh` (local bundle, per-user install), `quick-install.sh` (release bootstrap behind the README one-liner), `gen_keycodes.py`, `cue_audition.py`, `sound_asset_guard.py`. |
| `docs/` | `windows/SCOPE.md` (Windows backend scope), `code-smells.md` / `refactoring-techniques.md` (review/refactor references), `cue-audition.md`. |

The ASR model (~1.5 GB) is never bundled — `stenographer model download`
fetches it once; `asr.hotwords` require a full (non-distil) model.
