# VERIFIED — 35-live-docs-packaging

Verifier re-run on 2026-10-19 at commit e6a5a9c, from the worktree root. The
worktree had no `.venv`; the verifier created one with
`python3 -m venv .venv && .venv/bin/pip install -e ".[dev,build]"` (Python 3.14.8).
No microphone, system capture, integration test, or model download ran.

| Item | Result | Observation |
| --- | --- | --- |
| Gate: `ruff check .` | pass | `All checks passed!` |
| Gate: `ruff format --check .` | pass | `578 files already formatted` |
| Gate: `pytest -m "not integration"` | pass | `2538 passed, 2 skipped, 6 deselected` (skips need absent public clips) |
| Gate: `stenographer --help` | pass | exit 0; subcommands include `live` |
| `scripts/check-completions.sh` | pass | `completion checks passed: bash` (zsh, fish not installed) |
| `scripts/check_site.sh` | pass | exit 0 on a temp site assembled as in `.github/workflows/pages.yml` |
| `scripts/build.sh` | pass | exit 0, `built: dist/stenographer/stenographer`; log ends `Build complete!` |
| Bundle contents | pass | `textual/`, `sherpa_onnx/`, `libsherpa-onnx-c-api.so`, `libsherpa-onnx-cxx-api.so`, `_sherpa_onnx.cpython-314-x86_64-linux-gnu.so`, `libonnxruntime.so` present |
| Built `live --help` | pass | exit 0; matches V2.md output |
| Built `model download --help` | pass | exit 0; lists `--asr`, `--refine`, `--live` |
| No `evidence/` in build output | pass | `find dist build -path '*evidence*'` empty; `grep -c evidence dist/build.log` = 0. `python -m build` is not installed in the venv, so the sdist variant was not run (the brief accepts either). |
| `evidence/` removed from `pyproject.toml` exclude and `.gitignore` | pass | `grep evidence pyproject.toml .gitignore` empty; 33 evidence files remain tracked |
| `docs/live.md` required statements | pass | echo out of scope + headphones / `--no-mic` / `m`; `run` and `live` together, each loads a model; transcript + audio, files `0600` (matches `session_writer.py`); labels split/merge, `r` merges; full system mix only; PipeWire + `pw-record`; ~2 s decode and 0.50 threshold on 3 clips; FLAC `PCM_24` |
| README, usage, architecture (`lib/live/`), site, CHANGELOG | pass | entries and links present |
| `AGENTS.md` privacy amendment | **fail** | Exception is present and the file is 299 words, but the branch rewrites every bullet and several existing rules lose or change meaning (below). |

## AGENTS.md meaning changes (dev → branch)

1. `Develop on \`dev\`. Use conventional commits …` became
   `On \`dev\`, use conventional commits …`. The rule to develop on `dev` is lost;
   the text now only scopes commit style.
2. `Keep ordinary classes in their own files` became
   `Put each class in its own file`. The rule now covers every class, which
   conflicts with the next sentence that lets related dataclasses share files.
3. `Split by responsibility and navigability` became `Split by responsibility`.
   The navigability criterion is dropped.
4. `Core code and provider imports must remain portable` became
   `Keep core and provider imports portable`. Portability of core code is
   narrowed to imports only.
5. `see new regression tests fail before fixing behavior` became
   `make regression tests fail before fixing behavior`. "new" is dropped, and
   "see … fail" (observe) became "make … fail".

The brief asks only to amend the privacy rule, and no rule may lose or change
meaning. A minimal amendment is about 309 words, so some tightening is needed,
but it must keep each rule's meaning.

## Verdict

fail — the AGENTS.md requirement. Every other item passes.
