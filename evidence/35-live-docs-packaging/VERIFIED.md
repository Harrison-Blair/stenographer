# VERIFIED — 35-live-docs-packaging

Second verifier run on 2026-10-19 at commit b29fc91, from the worktree root,
after the repair of the AGENTS.md finding from the first run (9c23544). No
microphone, system capture, integration test, or model download ran.

| Item | Result | Observation |
| --- | --- | --- |
| Gate: `ruff check .` | pass | `All checks passed!` |
| Gate: `ruff format --check .` | pass | `578 files already formatted` |
| Gate: `pytest -m "not integration"` | pass | `2538 passed, 2 skipped, 6 deselected` (skips need absent public clips in `tmp/live_audio`) |
| Gate: `stenographer --help` | pass | exit 0 |
| `scripts/check-completions.sh` | pass | `completion checks passed: bash` (zsh, fish not installed) |
| `scripts/check_site.sh` | pass | exit 0 on a temp site assembled as in `.github/workflows/pages.yml`; temp dir removed |
| `scripts/build.sh` | pass | exit 0, `built: dist/stenographer/stenographer`; log ends `Build complete!` |
| Bundle contents | pass | `textual/`, `sherpa_onnx/`, `libsherpa-onnx-c-api.so`, `libsherpa-onnx-cxx-api.so`, `_sherpa_onnx.cpython-314-x86_64-linux-gnu.so`, `libonnxruntime.so` present |
| Built `live --help` | pass | exit 0; output matches V2.md |
| Built `model download --help` | pass | exit 0; lists `--asr`, `--refine`, `--live` |
| No `evidence/` in build output | pass | `find dist build -path '*evidence*'` empty; `grep -c evidence dist/build.log` = 0. The `build` package is not installed, so the sdist variant was not run (the brief accepts either). |
| `evidence/` removed from `pyproject.toml` exclude and `.gitignore` | pass | `grep evidence pyproject.toml .gitignore` empty; 35 evidence files tracked |
| `docs/live.md` required statements | pass | echo out of scope + headphones / `--no-mic` / `m`; `run` and `live` together, each loads its own model; transcript + audio, files `0600` (matches `session_writer.py`); labels split/merge, `r` merges; full system mix only; PipeWire + `pw-record`; ~2 s decode and 0.50 threshold on three clips; FLAC `PCM_24` |
| README, usage, architecture (`lib/live/`), site, CHANGELOG | pass | entries and links to `docs/live.md` present |
| `AGENTS.md` privacy amendment | pass | 299 words. Keeps `Never put transcript text or audio in logs or history`, adds analytics, and adds the live exception limited to the session folder with a link to `docs/live.md`. The five meaning changes from the first run are repaired: `Develop on \`dev\``, `ordinary classes`, `responsibility and navigability`, `Core code and provider imports must remain portable`, `see new regression tests fail` are all restored. Remaining edits against `dev` are wording only (checked line by line). |

## Verdict

pass — every item matches the expected output.
