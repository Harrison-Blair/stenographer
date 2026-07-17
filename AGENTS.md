# AGENTS.md

## Current state

The project is a Wayland push-to-talk / toggle dictation daemon. The
whole tree — `src/`, `tests/`, `packaging/`, `scripts/`, `BUILD.md` —
is committed and released (current version in `pyproject.toml`).

Key tracked paths:

- `README.md` — project readme (user-owned description + auto-generated
  install / run / configure sections; do not edit above the "DO NOT EDIT"
  line).
- `BUILD.md` — standalone-binary build instructions.
- `LICENSE` — GNU GPL v3-or-later.
- `.python-version` — pins Python 3.14 (consumable by `pyenv` / `uv`).
- `pyproject.toml` — project metadata, runtime + dev + build
  `optional-dependencies`, hatchling build, ruff config, pytest
  config (with an `integration` marker, opt-in via
  `STENOGRAPHER_INTEGRATION=1`).
- `src/stenographer/` — the package (cli, `_parser`, session,
  capabilities, config, errors, notification, update, bench, and the
  `hotkey/`, `audio/`, `asr/`, `output/` subpackages + `assets/`).
- `tests/` — pytest suite mirroring `src/` plus `tests/fixtures/`.
- `packaging/` — `stenographer.service.in` (systemd user unit template),
  `stenographer.spec` (PyInstaller), PyInstaller hooks, bash completion.
- `scripts/` — `build.sh`, `install.sh`, `build-and-install.sh`,
  `install-hooks.sh`, `download_model.py`, `gen_cues.py`.
- `.github/workflows/release.yml` — release CI (runs on merge to `main`).

Gitignored: `.venv/` (the project virtualenv; see **Tooling**), and
`build/` / `dist/` (PyInstaller working / output directories).

The release workflow lives at `.github/workflows/release.yml` and runs on
every merge to `main` (plus `workflow_dispatch`): it lints, tests, builds the
binary, and publishes a `v<version>` release. Features are developed on the
`dev` branch and merged to `main` to release; each such merge must bump
`[project].version` in `pyproject.toml`.

## Tooling

The project venv is `.venv/` (gitignored) and the Python version pin
is `.python-version` (3.14).

- **Run Python via the venv.** Do not use the system `python` /
  `pip` for project work.
  - Direct: `.venv/bin/python ...`
  - Or activate first (`source .venv/bin/activate`), then use
    `python` / `pip` as usual.
- **Lint and format with the venv's `ruff`.** Never rely on a
  system-installed `ruff`.
  - `.venv/bin/ruff check .`
  - `.venv/bin/ruff format .`
  - `.venv/bin/ruff check --fix .` for autofixes.
- **Test with the venv's `pytest`.** Two marker buckets:
  - default (`-ra`) — fast, no environment dependencies.
  - `integration` — touches the user's clipboard / audio / display.
    Skipped unless `STENOGRAPHER_INTEGRATION=1` is set in the
    environment.
  - Run all: `.venv/bin/pytest`
  - Run unit only: `.venv/bin/pytest -m "not integration"`
- **Verification before committing changes to code.** Run both
  `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .`
  and resolve any reported issues. For code-touching changes, also
  run `.venv/bin/pytest -m "not integration"` and confirm green.
- **Recreating the venv.** If `.venv/` is missing or stale:
  `python3 -m venv .venv && .venv/bin/pip install -e ".[dev,build]"`.
  The `dev` extra pulls in `ruff` and `pytest`; the `build` extra
  pulls in `pyinstaller` for the standalone binary.
- **Building the standalone binary.** `scripts/build.sh` (wraps
  `pyinstaller --noconfirm --clean packaging/stenographer.spec`).
  Output: `dist/stenographer/stenographer`. Runtime system
  requirements on the target machine: `wtype`, `wl-clipboard`,
  `pipewire` (or `pulseaudio`), `libevdev1`, `libportaudio2`,
  `libnotify` (`notify-send`), plus the user's `input` group
  membership. See `BUILD.md`.

## Post-change workflow

After modifying any source file under `src/` or `tests/`, run through these
steps in order:

1. **Lint and format.**
   ```
   .venv/bin/ruff check . && .venv/bin/ruff format --check .
   ```
   Use `.venv/bin/ruff check --fix .` to auto-fix fixable issues.
2. **Run unit tests.**
   ```
   .venv/bin/pytest -m "not integration"
   ```
3. **Build the standalone binary.**
   ```
   scripts/build.sh
   ```
   Output goes to `dist/stenographer/stenographer`.

## Development workflow

The code and tests are the source of truth. `session.py`
is the orchestrator that wires the components together — start there when
tracing behaviour.

**New feature or new component.** Add the module under the matching
subpackage (`hotkey/`, `audio/`, `asr/`, `output/`, or top-level for
cross-cutting concerns), give it a docstring describing its contract,
mirror it with a `tests/test_*.py`, and wire it into `Session` /
`cli.py`. Every new source file carries the SPDX header.

**Requirement or behaviour change.** Change the code and update the
tests that pin the old behaviour in the same change. If the change
touches config, keep the `Config` dataclass, `doctor`, and the README's
generated config section in sync.

**Bug fix.** Write a test that reproduces the bug (confirm it fails
against the unfixed code), then fix.

## Established stack

These decisions are baked into `pyproject.toml`.

- **Stack:** Python 3.14 CLI daemon.
- **Layout:** `src/stenographer/` (src-layout); `tests/` mirrors
  the package layout.
- **Project metadata:** `pyproject.toml` is the single source of
  truth. Built with `hatchling`.
- **Tests:** `pytest`, with `pytest-asyncio` available and an
  `integration` marker. Run via the venv.
- **Types:** not yet enforced. `mypy` or `pyright` is a future addition.
- **License:** GPL-3.0-or-later — every new source file MUST carry
  `SPDX-License-Identifier: GPL-3.0-or-later` at the top.
- **Distribution:** `pip install` (or `pipx install`) via the wheel
  built from `pyproject.toml`; **and** a PyInstaller `--onedir`
  binary at `dist/stenographer/stenographer` for users who do not
  want a `pip install` at all. The ASR model (~800 MB) is **not**
  bundled; users fetch it once with `stenographer model download`.

## Where to look

When in doubt, read the code in this order:

1. `src/stenographer/session.py` — the orchestrator; how one utterance
   flows hotkey → record → transcribe → output.
2. `src/stenographer/cli.py` + `_parser.py` — CLI surface, subcommands,
   process lifecycle, signals, single-instance lock.
3. The component module for the area being changed:
   `hotkey/` (binding, listener, state machine), `audio/` (capture,
   feedback), `asr/` (model, worker), `output/` (inject,
   clipboard).
4. `config.py` — config schema (including `[stenographer.update]`).
5. `errors.py` — degradation policy and exit codes.
6. `capabilities.py` — the `doctor` probe.
7. `update.py` — the `update` subcommand (GitHub Releases transport,
   onedir self-replace, daemon stop / start).
8. `README.md` / `BUILD.md` — install, run, and packaging behaviour.

## When this file goes stale

- If `.venv/` is recreated with different packages, or
  `.python-version` is bumped, keep the **Tooling** block in sync.
- If `pyproject.toml` changes (new optional-dependency, new
  pytest marker, ruff rule change, hatch config), keep the
  **Established stack** and **Tooling** blocks in sync.
- If a new component is added to `src/`, mirror it under `tests/`
  and reference it in **Where to look**.
- If CI is added, document required services, env vars, and test
  prerequisites here.
- If a new top-level layout decision is made (e.g. monorepo,
  separate `cli/` package), update **Established stack**.
