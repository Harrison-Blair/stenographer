# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`stenographer` is a Wayland, local-only push-to-talk dictation daemon. Hold a
global hotkey, speak, release: the recognized text is copied to both Wayland
selections (`wl-copy`) and pasted at the cursor via a `uinput` Shift+Insert
chord — display-server-independent, so it works on wlroots compositors and
GNOME alike. Hold is the default; `hotkey.mode = "toggle"` presses once to
start and again to stop. Offline, English-only, GPL-3.0-or-later, Python ≥ 3.12.

This is the reauthored codebase (2026-08): a clean-room rewrite of the original
~9k-line tool down to ~2k lines. `docs/reauthor.md` is the design record — its
§2 decisions are settled, its §4 behavioral knowledge inventory binds every
change, and its §6 testing policy is codified below. Do not reintroduce cut
features (transcript preview/the old HUD, the hybrid trigger mode, self-update,
release distribution) without revisiting that document's §7 add-later ledger.
The isolated lifecycle pill—with exactly 18 live spectrum bars while recording
and a helper-local amber border pulse only while the model loads—and local
PyInstaller onedir build are the documented exceptions, not general permission
to restore the old GUI or distribution surface.

## Commands

All Python tooling runs through the repo venv (`.venv/`, gitignored). **Never
use the system `python` / `pip` / `ruff` / `pytest`.** Recreate the venv with:

```sh
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

- **Lint / format:** `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .`
  (`.venv/bin/ruff check --fix .` to autofix).
- **Test (unit):** `.venv/bin/pytest -m "not integration"`
- **Test (all, incl. env-touching):** `STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest`
- **Single test:** `.venv/bin/pytest tests/test_daemon.py::test_name`
- **CLI smoke:** `.venv/bin/stenographer --help` / `--version` /
  `.venv/bin/stenographer setup --help`

`integration`-marked tests touch the real clipboard / audio / uinput / model and
are skipped unless `STENOGRAPHER_INTEGRATION=1` is set.

## Testing policy (binding — docs/reauthor.md §6)

1. Unit tests cover **pure logic only** (formatter, config validation, gate
   math, protocol encode/decode, parser).
2. **No mocked-subprocess theater**: never write a test that mocks
   `subprocess` / `UInput` / `wl-copy` and asserts "we would have called it".
3. The **integration smoke suite is the real gate**: it genuinely creates a
   uinput device, writes the clipboard, plays cues, loads the model. Green
   smoke on a real machine precedes any dev → main merge.
4. Mock-only testability is a design smell — restructure the component
   (extract the pure part) instead of writing the mock.
5. A new pure-logic test only counts once it has been SEEN to fail against
   broken/stubbed behavior.

## Architecture

Flat package `src/stenographer/` (src-layout); `tests/` mirrors it.

- **`cli.py`** — argparse surface + lazy dispatch: `run`, `transcribe`,
  `model download`, `doctor`, `devices`, `setup`. Heavy imports (faster-whisper,
  sounddevice, evdev) stay inside subcommand handlers, never at module scope.
- **`setup.py`** — TTY-only, sectioned review of all 19 existing config keys,
  final save/cancel/re-edit decision, and post-save model/doctor/service guidance.
  It offers only `hold` and `toggle`; it never installs, enables, or starts an
  inactive service. A changed standard config may restart an already-active
  standard user service, but a custom `STENOGRAPHER_CONFIG` path never does.
- **`setup_config.py`** — tomlkit-backed preservation of comments, ordering,
  unknown content, and symlinks while materializing the complete schema. It
  validates through production `Config`, detects concurrent edits, creates an
  exact timestamped backup, and atomically preserves the target mode. Unchanged
  bytes are not written.
- **`calibration.py`** — one-shot, post-capture estimator for the existing
  `feedback.spectrum_floor_dbfs`. It uses the selected `Recorder`, never analyzes
  in the callback, and never affects capture, `min_speech_rms`, speech gating,
  ASR, persistence beyond that fixed key, or overlay IPC.
- **`daemon.py`** — the orchestrator: hotkey → record → transcribe → deliver;
  single-instance flock on `$XDG_RUNTIME_DIR/stenographer.lock`; signal
  handling. It prepares audio after taking the lock and before starting the
  listener. Capture starts before the `record_start` cue, then a background
  worker request warms a cold model while recording continues. Capture stops
  and secures samples before the `record_stop` cue. One utterance at a time. In
  toggle mode a generation-guarded timer ends the session at
  `audio.max_recording_seconds` through the same stop path.
- **`hotkey.py`** — evdev hotkey listener: chord parse, main-keyboard
  auto-detection, rescan on read error. Reports chord edges; the daemon maps
  them to session actions per `hotkey.mode`. Requires `input` group.
- **`audio.py`** — PortAudio recorder: pre-negotiates and retains a stopped
  stream for reuse across captures; block-copy callback with a latest-only
  handoff to the optional overlay supervisor (no analysis in the callback), RMS
  speech gate (two consecutive 50 ms frames — see the quiet-mic note in
  docs/reauthor.md §4.1), sample-rate fallback + resample. A stale retained
  stream gets one close/renegotiate/start recovery attempt.
- **`worker.py`** — ASR child process: one job at a time, killed after
  `asr.idle_unload_seconds`, respawned on demand, crash-isolated from the
  daemon. It supports a load-only request on recording start; decode serializes
  behind an unfinished warm-up, and idle eviction is held through the recording
  pipeline. Child logs cross a multiprocessing queue to parent-owned handlers;
  the child never opens the rotating file. Results carry word timestamps (keeps
  the streaming door open).
- **`status.py`** — fixed lifecycle states plus the strict protocol v4 NDJSON
  contract and pure generation/coalescing policy. Its variable records are 18
  quantized levels for the current recording generation and a model-loading
  boolean; pulse timing stays helper-local, with no transcript or raw-audio payloads.
- **`spectrum.py`** — pure daemon-side 32 ms Hann/zero-padded FFT band analysis at
  60 fps, fixed configurable-floor-to-−12 dBFS mapping, 2.5/22.5 ms smoothing,
  and 18-level quantization. It never affects the speech gate or recorded audio.
- **Overlay helper/backends** — optional isolated visual feedback: layer-shell
  preferred, XWayland fallback, click-through, and failure-disabled. No display
  or helper-process I/O may run under the daemon state lock.
- **`logging_setup.py`** — idempotent stderr + rotating state-file setup for
  every command; 5 MiB with three backups, `STENOGRAPHER_LOG_LEVEL`, and
  privacy-safe worker forwarding.
- **`model.py`** — faster-whisper wrapper: fixed anti-hallucination decode
  stack, output validation (`PathologicalOutputError`), `local_files_only` —
  the daemon never touches the network.
- **`deliver.py`** — copy to BOTH selections, confirm the copy, wait for
  physical hotkey release (a held modifier would corrupt the chord), then
  uinput Shift+Insert. A failed copy must never fire the chord.
- **`format.py`** — fixed zero-knob formatter (spacing, sentence caps, "i"→"I").
- **`feedback.py`** — four WAV cues via `canberra-gtk-play`, with `pw-play`/`paplay`
  fallbacks; degrades to no-op.
- **`doctor.py`** — capability probe; exit 78 when a required capability is
  missing. `notify.py` — `notify-send` errors, no-op if absent.
- **`config.py`** — TOML config, exactly 19 keys in 4 sections (`hotkey`,
  `audio`, `asr`, `feedback`), frozen dataclasses, key-scoped `ConfigError` →
  exit 78, missing file written with annotated defaults, and an in-memory load
  path used to validate setup output. No migrations or extra setup-only keys.
  `hotkey.mode` (`hold` | `toggle`) defaults to `hold`. `feedback.overlay`
  defaults true and controls only the optional visual surface;
  `feedback.spectrum_floor_dbfs` defaults to −45.0 dBFS.

`stenographer setup` requires a TTY: non-TTY exits 2, normal cancellation exits
0, and Ctrl-C/EOF exits 130. Invalid existing configuration and missing required
doctor capabilities exit 78; write, download, probe, and restart failures exit 1.
After saving, failures are reported without rolling configuration back. Automatic
floor calibration is a static five-second room-noise measurement after a silent
three-second countdown: discard 0.5 seconds, measure non-overlapping 32 ms windows,
take each band's 95th percentile, use the loudest +3 dB rounded upward, clamp quiet
valid results to −96 dBFS, and reject results above −13 dBFS plus short, digitally
silent, or strongly nonstationary captures. It is not rolling calibration or
speech-gate calibration.

The ASR model (~1.5 GB) is **never** bundled — `stenographer model download`
fetches it once. `asr.hotwords` require a full (non-distil) model.

## Conventions

- Every source file carries `SPDX-License-Identifier: GPL-3.0-or-later` at the top.
- ruff: line length 100, target py312, rules `E,F,I,B,UP,N,SIM,RUF`. All code
  must stay Python-3.12-compatible.
- `pyproject.toml` (hatchling) is the single source of truth for metadata/deps.
- Develop on `dev`; merge to `main` only after the integration smoke suite and
  real dictation pass on a real machine.
- Logs may contain numeric/structural metrics and transcript lengths, never
  transcript text, audio, samples, or result representations.
