# AGENTS.md

Local, offline English dictation. Python ≥3.12; GPL-3.0-or-later.

- Use `.venv/bin/` for Python tools. Metadata, dependencies, lint settings:
  `pyproject.toml`. Source files need GPL SPDX headers.
- Keep Git/build allowlists synchronized; see docs/building.md.
  Refactoring: `docs/reference/guru/`.
- User-facing changes update README.md, owning docs, and Pages site (`site/`).
- Production code lives in `lib/`, `cli/<command>/`, and `overlay/`.
  CLI workflows connect independent library engines and overlay services;
  `lib/` imports neither CLI nor overlay code. Put native code behind
  contracts in `lib/platform/` or `overlay/platform/`.
  Core code and provider imports must remain portable on Linux.
- Keep ordinary classes in their own files without standalone helpers.
  Related dataclasses may share files; related exceptions share domain
  `errors.py`. Keep errors with their domain; shared ones belong in
  `lib/utils/errors.py`. Split by responsibility and navigability; no size
  limit. Keep resources in `assets/`.
- Dictation stays offline; model downloads are explicit. The daemon's only
  network calls are the metadata-only update notice and
  loopback-by-default refine request (docs/refine.md). Never put transcript
  text or audio in logs or history or analytics. `stenographer live` may write
  both only to the user-requested session folder (docs/live.md).
- Preserve configuration compatibility; use the preservation layer for saves.
- Unit-test pure logic; see new regression tests fail before fixing behavior.
  Test native behavior on real platforms, not mock OS calls. Never enable
  integration tests in CI/sandboxes or access the microphone without explicit
  consent.
- Develop on `dev`. Use conventional commits without attribution trailers.
  Merging to `main` requires real-machine acceptance.
- After verification, offer `scripts/reinstall.sh`; run when authorized and
  report result.

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
