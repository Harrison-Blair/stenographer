# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`stenographer` is a Wayland, local-only push-to-talk dictation daemon. Hold a
global hotkey, speak, release: the recognized text is copied to both Wayland
selections (`wl-copy`) and pasted at the cursor via a `uinput` Shift+Insert
chord — display-server-independent, so it works on wlroots compositors and
GNOME alike. Offline, English-only, GPL-3.0-or-later, Python ≥ 3.12.

This is the reauthored codebase (2026-08): a clean-room rewrite of the original
~9k-line tool down to ~2k lines. `docs/reauthor.md` is the design record — its
§2 decisions are settled, its §4 behavioral knowledge inventory binds every
change, and its §6 testing policy is codified below. Do not reintroduce cut
features (visualizer/HUD, incremental preview, toggle/hybrid modes, self-update,
PyInstaller packaging) without revisiting that document's §7 add-later ledger.

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
- **CLI smoke:** `.venv/bin/stenographer --help` / `--version`

`integration`-marked tests touch the real clipboard / audio / uinput / model and
are skipped unless `STENOGRAPHER_INTEGRATION=1` is set.

Run the git hooks once after cloning (`./scripts/install-hooks.sh`) so
`ruff format` runs on staged Python at commit time.

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

- **`cli.py`** — argparse surface + dispatch: `run`, `transcribe`,
  `model download`, `doctor`, `devices`. Heavy imports (faster-whisper,
  sounddevice, evdev) stay inside subcommand handlers, never at module scope.
- **`daemon.py`** — the orchestrator: hotkey → record → transcribe → deliver;
  single-instance flock on `$XDG_RUNTIME_DIR/stenographer.lock`; signal
  handling. One utterance at a time.
- **`hotkey.py`** — evdev PTT listener: chord parse, main-keyboard
  auto-detection, rescan on read error. Requires `input` group.
- **`audio.py`** — PortAudio recorder: block-copy callback (no analysis in the
  callback), RMS speech gate (two consecutive 50 ms frames — see the quiet-mic
  note in docs/reauthor.md §4.1), sample-rate fallback + resample.
- **`worker.py`** — ASR child process: one job at a time, killed after
  `asr.idle_unload_seconds`, respawned on demand, crash-isolated from the
  daemon. Results carry word timestamps (keeps the streaming door open).
- **`model.py`** — faster-whisper wrapper: fixed anti-hallucination decode
  stack, output validation (`PathologicalOutputError`), `local_files_only` —
  the daemon never touches the network.
- **`deliver.py`** — copy to BOTH selections, confirm the copy, wait for
  physical hotkey release (a held modifier would corrupt the chord), then
  uinput Shift+Insert. A failed copy must never fire the chord.
- **`format.py`** — fixed zero-knob formatter (spacing, sentence caps, "i"→"I").
- **`feedback.py`** — five WAV cues via `pw-play`/`paplay`; degrades to no-op.
- **`doctor.py`** — capability probe; exit 78 when a required capability is
  missing. `notify.py` — `notify-send` errors, no-op if absent.
- **`config.py`** — TOML config, 4 sections (`hotkey`, `audio`, `asr`,
  `feedback`), frozen dataclasses, key-scoped `ConfigError` → exit 78, missing
  file written with annotated defaults. No migrations.

The ASR model (~1.5 GB) is **never** bundled — `stenographer model download`
fetches it once. `asr.hotwords` require a full (non-distil) model.

## Conventions

- Every source file carries `SPDX-License-Identifier: GPL-3.0-or-later` at the top.
- ruff: line length 100, target py312, rules `E,F,I,B,UP,N,SIM,RUF`. All code
  must stay Python-3.12-compatible.
- `pyproject.toml` (hatchling) is the single source of truth for metadata/deps.
- Develop on `dev`; merge to `main` only after the integration smoke suite and
  real dictation pass on a real machine.
