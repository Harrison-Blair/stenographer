# AGENTS.md

## Current state

Tracked files:
- `README.md` — 2-line glossary entry for "stenographer"; no project description.
- `LICENSE` — GNU GPL v3.
- `.gitignore` — Python-flavored defaults (`__pycache__/`, `.venv/`, `.pytest_cache/`, `.ruff_cache/`, etc.).
- `.python-version` — pins Python 3.14 (consumable by `pyenv`/`uv`).
- `AGENTS.md` — this file.

Untracked infrastructure (gitignored):
- `.venv/` — Python virtual environment at the repo root, created with `python3 -m venv .venv`. Currently contains `ruff` only; see **Tooling**.

There is no source code, no `pyproject.toml`, no `requirements*.txt`, no `Makefile`, no CI, no test runner, and no `opencode.json`. No other `AGENTS.md`/`CLAUDE.md` files exist in subdirectories.

## Tooling

The project venv is `.venv/` (gitignored) and the Python version pin is `.python-version` (3.14).

- **Run Python via the venv.** Do not use the system `python`/`pip` for project work.
  - Direct: `.venv/bin/python ...`
  - Or activate first (`source .venv/bin/activate`), then use `python` / `pip` as usual.
- **Lint and format with the venv's `ruff`.** Never rely on a system-installed `ruff`.
  - `.venv/bin/ruff check .`
  - `.venv/bin/ruff format .`
  - `.venv/bin/ruff check --fix .` for autofixes.
- **Verification before committing changes to code.** Run both `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .` and resolve any reported issues.
- **Recreating the venv.** If `.venv/` is missing or stale: `python3 -m venv .venv && .venv/bin/pip install ruff`.

## Intended direction (aspirational — not yet enforced)

Treat as guidance for the first commits, not as established convention. Once a tool is actually configured, update the relevant line below to match.

- **Stack:** Python CLI and/or library.
- **Layout:** `src/<package>/` (src-layout) once the package name is chosen; `tests/` mirroring `src/`.
- **Project metadata:** `pyproject.toml` as the single source of truth.
- **Tests:** `pytest`.
- **Types:** `mypy` or `pyright`.
- **License:** GPL-3 — new source files should carry `SPDX-License-Identifier: GPL-3.0-or-later` at the top.

## Decide before writing the first code

The next agent should ask the user, not guess:
- Package import name (repo is `stenographer`; confirm before creating `src/stenographer/`).
- CLI command name and surface area.
- Whether the project will be published to PyPI.
- Minimum supported Python version.

## When this file goes stale

- If `.venv/` is recreated with different packages, or `.python-version` is bumped, keep the **Tooling** block in sync.
- If `pyproject.toml` is added, update the "Intended direction" section to match what it actually configures.
- If a different formatter, test runner, or type checker is chosen, update accordingly.
- If CI is added, document required services, env vars, or test prerequisites here.
- If a new top-level layout decision is made (e.g. flat module, monorepo), update "Layout".
