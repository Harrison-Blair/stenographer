---
id: FTHR-007
title: Bump version to 0.8.0
plumage: PLM-002
status: pipping
priority: P3
depends_on: []
authored: 2026-07-11T06:01:43Z
agent: fledge-orchestrate/planning
fledge_version: 0.4.0
---

# FTHR-007: Bump version to 0.8.0

## Description
Bump `[project].version` in `pyproject.toml` from `0.7.7` to `0.8.0`, per this repository's release convention (every merge to `main` must bump the version; the release workflow refuses to reuse an existing release tag). Satisfies PLM-002 FC-8.

## Affected Modules
Per `.fledge/nest/conventions.md` ("Release process": `pyproject.toml` is the single source of truth for `[project].version`; `.github/workflows/release.yml` requires a bump before it will publish):
- `pyproject.toml` — the sole file changed.
- `tests/test_config.py` or wherever `__version__`/version parsing is exercised, if any test hardcodes the current version string (none observed in `.fledge/nest/testing.md`'s inventory, but confirm at implementation time — `src/stenographer/__init__.py` reads `__version__` via `importlib.metadata` at runtime, not a hardcoded literal, so no source-code test dependency is expected).

## Approach
Single-line change: `version = "0.7.7"` → `version = "0.8.0"` in `pyproject.toml`. No other files should need changes — version is read dynamically via `importlib.metadata` at runtime (per `.fledge/nest/architecture.md`'s note on `__init__.py`), not duplicated anywhere else in source.

## Tests
- `test_pyproject_version_is_0_8_0` — a simple test (new, in whichever existing test module already touches `pyproject.toml`/packaging metadata, or a minimal new one) that reads `pyproject.toml` and asserts `[project].version == "0.8.0"`.

Implementation order: write the test, run it against the unchanged file and confirm it fails (current value is `0.7.7`), then make the one-line change until it passes.

## Acceptance Criteria
- [x] AC-1: The test listed above was observed failing before implementation and passes after.
- [x] AC-2: `pyproject.toml`'s `[project].version` reads `0.8.0` (satisfies PLM-002 FC-8, AC-6).
- [x] AC-3: `.venv/bin/pytest -m "not integration"` passes with no regressions.
