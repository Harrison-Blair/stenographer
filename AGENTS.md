# AGENTS.md

## Current state

This repo is a seed. Tracked files:
- `README.md` — 2-line glossary entry for "stenographer"; no project description.
- `LICENSE` — GNU GPL v3.
- `.gitignore` — Python-flavored defaults (`__pycache__/`, `.venv/`, `.pytest_cache/`, `.ruff_cache/`, etc.).

There is no source code, no `pyproject.toml`, no `requirements*.txt`, no `Makefile`, no CI, no test runner, no `opencode.json`, and no other `AGENTS.md`/`CLAUDE.md` files.

## Intended direction (aspirational — not yet enforced)

Treat as guidance for the first commits, not as established convention. Once a tool is actually configured, update the relevant line below to match.

- **Stack:** Python CLI and/or library.
- **Layout:** `src/<package>/` (src-layout) once the package name is chosen; `tests/` mirroring `src/`.
- **Project metadata:** `pyproject.toml` as the single source of truth.
- **Lint + format:** `ruff`.
- **Tests:** `pytest`.
- **Types:** `mypy` or `pyright`.
- **Python version:** pinned via `.python-version` (for `pyenv`/`uv`).
- **License:** GPL-3 — new source files should carry `SPDX-License-Identifier: GPL-3.0-or-later` at the top.

## Decide before writing the first code

The next agent should ask the user, not guess:
- Package import name (repo is `stenographer`; confirm before creating `src/stenographer/`).
- CLI command name and surface area.
- Whether the project will be published to PyPI.
- Minimum supported Python version.

## When this file goes stale

- If `pyproject.toml` is added, update the "Intended direction" section to match what it actually configures.
- If a different formatter, test runner, or type checker is chosen, update accordingly.
- If CI is added, document required services, env vars, or test prerequisites here.
- If a new top-level layout decision is made (e.g. flat module, monorepo), update "Layout".
