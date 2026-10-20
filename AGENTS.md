# AGENTS.md

Local, offline English dictation. Python ≥3.12; GPL-3.0-or-later.

- Use `.venv/bin/` for Python tools. `pyproject.toml` owns metadata,
  dependencies, and lint settings. Source files need the GPL SPDX header.
- Keep Git/build allowlists synchronized (docs/building.md).
  Refactoring: `docs/reference/guru/`.
- User-facing changes update README.md, owning docs, and the Pages site
  (`site/`).
- Production code lives in `lib/`, `cli/<command>/`, and `overlay/`. CLI
  workflows connect independent library engines and overlay services; `lib/`
  imports neither CLI nor overlay. Put native code behind contracts in
  `lib/platform/` or `overlay/platform/`. Keep core and provider imports
  portable across Linux, Windows, and macOS.
- Put each class in its own file without standalone helpers. Related
  dataclasses may share files; keep errors in domain `errors.py` files and
  shared errors in `lib/utils/errors.py`. Split by responsibility, with no
  size limit. Keep resources in `assets/`.
- Dictation stays offline; model downloads are explicit. The daemon's only
  network calls are the metadata-only update notice and loopback-by-default
  refine request (docs/refine.md). Keep transcript text and audio out of logs,
  analytics, and history. Exception: `stenographer live` session files are
  user-requested data; it writes text and audio only there (docs/live.md).
- Preserve configuration compatibility; use the existing preservation layer
  for saves.
- Unit-test pure logic; make regression tests fail before fixing behavior.
  Test native behavior on real platforms, not with mocked OS calls. Never
  enable integration tests in CI/sandboxes or access the microphone without
  explicit consent.
- On `dev`, use conventional commits without attribution trailers. Require
  real-machine acceptance to merge to `main`.
- After verification, offer `scripts/reinstall.sh`; run when authorized and
  report the result.

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
