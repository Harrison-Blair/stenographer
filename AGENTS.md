# AGENTS.md

Local, offline English dictation. Python ≥3.12; GPL-3.0-or-later.

- Use `.venv/bin/` for Python tools. Metadata, dependencies, lint settings:
  `pyproject.toml`. Source files need GPL SPDX headers.
- Keep Git/build allowlists synchronized; see docs/building.md.
- User-facing changes update README.md, owning docs, and Pages site (`site/`).
- Production code lives in `lib/`, `cli/<command>/`, and `overlay/`.
  CLI workflows connect independent library engines and overlay services;
  `lib/` imports neither CLI nor overlay code. Put native code behind
  contracts in `lib/platform/` or `overlay/platform/`.
  Core code and provider imports must remain portable on Linux.
- Small types and helpers may sit beside their single owner.
  Related exceptions share domain
  `errors.py`. Shared ones belong in
  `lib/utils/errors.py`. Split by responsibility and navigability; no size
  limit. Keep resources in `assets/`.
- Dictation stays offline; model downloads are explicit. The daemon's only
  network call is the loopback-by-default refine request (docs/refine.md).
  Never put transcript text or audio in logs, history, or analytics. The hub
  Record screen may write both only to the user-requested session folder
  (docs/hub.md).
- Preserve configuration compatibility; use the preservation layer for saves.
- Unit-test pure logic; see new regression tests fail before fixing behavior.
  Test native behavior on real platforms, not mock OS calls. Never enable
  integration tests in CI/sandboxes or access the microphone without explicit
  consent.
- Branch from `main`. Conventional commits, no attribution trailers. Merge
  only when asked or per approved plan. Real-machine acceptance precedes
  release; when asked to release, ask once whether the user tested.
- After verification, offer `scripts/reinstall.sh`; run when authorized and
  report result.

For code changes, run:

```sh
.venv/bin/ruff check .
.venv/bin/ruff format --check .
env -u NO_COLOR .venv/bin/pytest -m "not integration"
.venv/bin/stenographer --help
```

See README.md (usage), docs/building.md (packaging),
packaging/NATIVE-ACCEPTANCE.md (release acceptance).

Keep this file under 300 words. Put feature details in their owning docs.
