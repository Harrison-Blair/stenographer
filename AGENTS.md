# AGENTS.md

## Current state

The project is a Wayland push-to-talk / toggle dictation daemon
(`spec/00-overview.md`). Source of truth for design is the
`spec/` directory; the code under `src/`, the tests under `tests/`,
the build assets under `packaging/` and `scripts/`, and `BUILD.md`
all exist but are not yet committed.

Tracked in git:

- `README.md` — project readme (user description + auto-generated
  install / run / configure sections).
- `LICENSE` — GNU GPL v3-or-later.
- `.gitignore` — Python defaults plus `build/`, `dist/`, `*.spec.bak`
  for PyInstaller.
- `.python-version` — pins Python 3.14 (consumable by `pyenv` / `uv`).
- `pyproject.toml` — project metadata, runtime + dev + build
  `optional-dependencies`, hatchling build, ruff config, pytest
  config (with an `integration` marker, opt-in via
  `STENOGRAPHER_INTEGRATION=1`).
- `AGENTS.md` — this file.
- `spec/00-overview.md` … `spec/12-update.md` — thirteen spec docs
  that fix the shape, behaviour, build, and self-update of the
  system. The spec is canonical; the code must match it.
- `.github/workflows/release.yml` — release CI workflow (runs on merge to
  `main`; see `spec/11-ci-release.md`).

Present on disk but not yet committed (untracked):

- `BUILD.md` — standalone-binary build instructions.
- `src/stenographer/` — the package (cli, config, session,
  capabilities, errors, hotkey/, audio/, asr/, output/, assets/sounds/).
- `tests/` — pytest suite mirroring `src/` plus `tests/fixtures/`.
- `packaging/stenographer.service.in` — systemd user unit template.
- `packaging/stenographer.spec` — PyInstaller spec.
- `scripts/build.sh`, `scripts/download_model.py`, `scripts/gen_cues.py`.

Also gitignored:

- `.venv/` — Python virtual environment at the repo root, created
  with `python3 -m venv .venv`. Contains `ruff` and the dev /
  build extras; see **Tooling**.
- `build/`, `dist/` — PyInstaller working / output directories.

The release workflow lives at `.github/workflows/release.yml` and runs on
every merge to `main` (plus `workflow_dispatch`): it lints, tests, builds the
binary, and publishes a `v<version>` release. Features are developed on the
`dev` branch and merged to `main` to release; each such merge must bump
`[project].version` in `pyproject.toml`. See `spec/11-ci-release.md`.

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
  membership. See `BUILD.md` and
  `spec/10-packaging.md`.

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

## Spec-first workflow

The `spec/` directory is the source of truth. Code is downstream of spec.

**New feature or new component.** Before writing anything under
`src/` or `tests/`, draft a new spec doc in `spec/`. Use the next
free two-digit number prefix (currently `14-…`, after
`13-asset-retention.md`). Match the existing template:
`SPDX-License-Identifier: GPL-3.0-or-later` front matter, a
`## Dependencies` section listing which other spec docs this doc
consumes and which it blocks, and (for leaf components) a row in
the "Build order" DAG in `spec/00-overview.md`. Then implement.

**Requirement change that affects an existing spec doc.** Edit the
relevant spec doc first. Update its `## Dependencies` and any DAG
rows in `00-overview.md` that it touches. Then change the code. If
the change crosses docs (e.g. config schema + process model), update
all of them before writing code.

**Pure bug fix that the spec already covers.** No spec edit needed;
fix the code so it matches the spec.

**Conflict.** Spec wins. If code disagrees with spec, fix the code;
if you believe the spec is wrong, open an "Open questions" item in
the relevant spec doc and ask before changing the spec.

## Established stack

These decisions are baked into `pyproject.toml` and the spec, and
are not open to renegotiation without a spec change.

- **Stack:** Python 3.14 CLI daemon.
- **Layout:** `src/stenographer/` (src-layout); `tests/` mirrors
  the package layout.
- **Project metadata:** `pyproject.toml` is the single source of
  truth. Built with `hatchling`.
- **Tests:** `pytest`, with `pytest-asyncio` available and an
  `integration` marker. Run via the venv.
- **Types:** not yet enforced. `mypy` or `pyright` is a future
  addition; the spec does not require it.
- **License:** GPL-3.0-or-later — every new source file MUST carry
  `SPDX-License-Identifier: GPL-3.0-or-later` at the top.
- **Distribution:** `pip install` (or `pipx install`) via the wheel
  built from `pyproject.toml`; **and** a PyInstaller `--onedir`
  binary at `dist/stenographer/stenographer` for users who do not
  want a `pip install` at all. The ASR model (~800 MB) is **not**
  bundled; users fetch it once with `stenographer model download`.

## Authoritative references

When in doubt, read these in order:

1. `spec/00-overview.md` — shape, glossary, capability probe.
2. The component spec for the area being changed
   (`01-hotkey`, `02-audio-capture`, `03-transcription`,
   `04-audio-feedback`, `05-text-output`, `06-clipboard`).
3. `spec/07-configuration.md` — config schema (including
   `[stenographer.update]`).
4. `spec/08-process-model.md` — CLI surface, lifecycle, signals,
   the `update` subcommand.
5. `spec/09-error-handling.md` — degradation policy and exit codes
   (including `UpdateError` and the network / sha256 / systemd
   rows).
6. `spec/10-packaging.md` — deps, asset layout, PyInstaller,
   systemd.
7. `spec/11-ci-release.md` — the GitHub Actions release workflow
   and the tag ↔ version contract.
8. `spec/12-update.md` — the `update` subcommand: GitHub Releases
   transport, onedir self-replace, daemon stop / start.

The code MUST match the spec; if it does not, the spec wins (open
a question in the relevant spec doc and fix the code).

## When this file goes stale

- If `.venv/` is recreated with different packages, or
  `.python-version` is bumped, keep the **Tooling** block in sync.
- If `pyproject.toml` changes (new optional-dependency, new
  pytest marker, ruff rule change, hatch config), keep the
  **Established stack** and **Tooling** blocks in sync.
- If a new component is added to `src/`, mirror it under `tests/`
  and reference its spec doc in **Authoritative references**.
- If a spec doc is added, renumbered, or split, update both the
  tracked-files list and **Authoritative references**.
- If CI is added, document required services, env vars, and test
  prerequisites here.
- If a new top-level layout decision is made (e.g. monorepo,
  separate `cli/` package), update **Established stack**.
