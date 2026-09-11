# AGENTS.md

Local, offline English dictation. Python ≥3.12; GPL-3.0-or-later.

- Use `.venv/bin/` for all Python tooling. Metadata, dependencies, and lint
  settings live in `pyproject.toml`. Source files need the GPL SPDX header.
- Keep Git/build allowlists synchronized; see docs/building.md. Refactoring references:
  `docs/reference/guru/`.
- User-facing changes update README.md, owning docs, and the Pages site
  (`site/`).
- Organize production code under `lib/`, `cli/<command>/`, and `overlay/`.
  CLI workflows connect independent library engines and overlay services;
  `lib/` imports neither CLI nor overlay code. Native code stays behind
  contracts in `lib/platform/` or `overlay/platform/`. Core code and provider
  imports must remain portable across Linux, Windows, and macOS.
- Keep ordinary classes in their own files without standalone helpers.
  Related dataclasses may share files; related exceptions share domain
  `errors.py`. Keep errors with their domain; general shared errors belong
  in `lib/utils/errors.py`. Split by responsibility and navigability, without
  a numeric size limit. Keep resources in `assets/`.
- Dictation stays offline; model downloads are explicit. The existing
  metadata-only update notice is the daemon's sole network exception.
  Never put transcript text or audio in logs or history.
- Preserve configuration compatibility and use the existing preservation
  layer for saves.
- Unit-test pure logic; see new regression tests fail before fixing behavior.
  Test native behavior on real platforms instead of mocking OS calls.
  Never enable integration tests in CI/sandboxes or access the physical
  microphone without explicit consent.
- Develop on `dev`. Use conventional commits without attribution trailers.
  Merging to `main` requires real-machine acceptance.
- After verified application changes, offer `scripts/reinstall.sh`; run it
  when authorized and report the result.

For code changes, run:

```sh
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest -m "not integration"
.venv/bin/stenographer --help
```

See README.md for usage, docs/building.md for packaging, and
packaging/NATIVE-ACCEPTANCE.md for release acceptance.

Keep this file under 300 words. Put feature details in their owning docs.
