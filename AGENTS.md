# AGENTS.md

Guidance for AI agents working in this repository. `CLAUDE.md` carries the
canonical command reference and architecture map; this file adds the rules an
agent must not learn the hard way. When the two disagree, `CLAUDE.md` wins.

## What you are working on

A Wayland push-to-talk dictation daemon: hold a hotkey, speak, release — the
transcript is copied to both Wayland selections and pasted at the cursor via a
`uinput` Shift+Insert chord. Offline, English-only, Python ≥ 3.12,
GPL-3.0-or-later.

The codebase is ~2k lines, with a flat package in `src/stenographer/` and tests
in `tests/`. `docs/reauthor.md` is the binding design record: its §2 decisions
are settled, §4 is the behavioral knowledge inventory
that binds every change, §6 is the testing policy, §7 lists deliberately cut
features. Do not reintroduce cut features (old HUD, transcript preview,
toggle/hybrid modes, self-update, PyInstaller packaging, wtype) without that
document being revised first. The sole visual exception is the isolated
lifecycle pill documented in decisions §2.15/§4.17. Its only animations are
exactly 18 locally analyzed spectrum bars while recording and a 2-second amber
breathing border while the model is actively loading; state interiors stay
fixed. It must never grow transcript preview, controls, GTK, or raw-audio IPC.

## Layout

- `src/stenographer/` — core modules at the root (`daemon`, `hotkey`, `audio`,
  `config`, `status`) plus subpackages: `cli/` (surface, `commands/`, setup and
  doctor engines), `transcribe/` (`worker`, `model`, `format`), `overlay/`
  (supervisor, backends, `protocols/`), `delivery/` (`deliver`, `feedback`,
  `notify`), `utils/`, and `assets/` (WAV cues, icon, font, native completions).
- `tests/` — mirrors the subpackage grouping; unit tests (pure logic) plus
  `test_*_smoke.py` integration tests.
- `packaging/stenographer.service` — the systemd user unit.
- `scripts/build.sh` / `scripts/install.sh` — local bundle and per-user install.
- `docs/` — `reauthor.md` (design record), `code-smells.md` and
  `refactoring-techniques.md` (review/refactor references).

## Hard rules

1. **Venv only.** Every tool runs as `.venv/bin/...` (`pip`, `ruff`, `pytest`).
   Never system Python. Recreate with
   `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`.
2. **Python 3.12 compatibility.** ruff targets py312; no 3.13+/3.14-only syntax.
3. **SPDX header** (`GPL-3.0-or-later`) on every source file.
4. **Testing policy is binding** (docs/reauthor.md §6): unit tests for pure
   logic only; never mock `subprocess`/`UInput`/`wl-copy` to assert a call
   would have happened; a new pure-logic test must be SEEN to fail against
   broken behavior; the integration smoke suite
   (`STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest`) is the real gate and needs a
   real machine — do not set that variable in CI or sandboxes.
5. **Behavioral invariants** (docs/reauthor.md §4) — the ones most often at
   risk in edits: never gate audio on absolute RMS defaults (quiet-mic rule);
   the paste chord fires only after a confirmed clipboard copy AND physical
   hotkey release; the daemon never touches the network (`local_files_only`);
   the PortAudio callback only copies blocks; logs never contain transcript
   text or audio.
6. **Narrow distribution boundary.** The local PyInstaller onedir build,
   single-machine per-user installer, and `main`-only x86_64/AArch64 draft
   release workflow are allowed. Self-update, automatic publishing,
   and multi-distro installers remain cut. Static Bash, Zsh, and Fish
   completions are allowed; keep them dependency-free and discovery-free.
7. **Overlay isolation.** The optional helper may receive only fixed lifecycle
   metadata, a model-loading active/inactive boolean, and 18 quantized spectrum
   levels over the versioned protocol. Pulse timing is helper-local. Raw microphone
   samples stay in the daemon-side supervisor; the helper remains click-through
   and must degrade to disabled without affecting daemon success. Never put
   analysis/display/process I/O under daemon locks or send transcript, raw audio,
   device/model names, config values, or detailed errors across IPC.
8. **Branch model.** Develop on `dev`. Merging to `main` requires the smoke
   suite and real dictation to pass on a real machine first.
9. **Commits** are conventional (`feat:`, `fix:`, `chore:`) with no
   attribution trailers. Run the quick verification loop before committing.

## Quick verification loop

```sh
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest -m "not integration"
.venv/bin/stenographer --help
```
