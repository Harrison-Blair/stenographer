# VERIFIED — 60-hub-shell

Verifier run on 2026-10-19 at `cc484fe` (base `13d95fd`). The worktree has no
`.venv`, so the verifier used `/home/penguin/source/stenographer/.venv/bin`
(Python 3.14.8, Textual 8.2.8) with `PYTHONPATH="$PWD/src"`; the import
resolved to this worktree's `src/stenographer`. Each item was re-run with the
commands in `V<n>.md`.

| Item | Result | Observation |
| --- | --- | --- |
| V1–V4 red: `pytest tests/cli/hub` on base `13d95fd` (temporary worktree, new tests copied in) | pass | Collection error, `ModuleNotFoundError: No module named 'stenographer.cli.hub'` |
| V1 green: `test_handler.py -k 'bare_command or argument_separator'` | pass | `5 passed, 3 deselected` |
| V1 live: bare `stenographer </dev/null` (non-TTY) | pass | exit 0, `usage: stenographer` printed |
| V1 live: bare `stenographer` in a pseudo-TTY, press `q` | pass | Hub drew Live, Files, Sessions, Config, Setup, Doctor and "Press space"; `q` quit with exit 0 before recording. Worker warm-up ran before the app |
| V2 green: `test_app.py -k navigation` | pass | `1 passed, 2 deselected` |
| V3 green: `test_app.py -k quit` | pass | `2 passed, 1 deselected` |
| V3 green: `test_handler.py -k 'services_'` | pass | `2 passed, 6 deselected` |
| V4 green: `test_handler.py -k warms_worker` | pass | `1 passed, 7 deselected` |
| V5 `ruff check .` | pass | `All checks passed!` |
| V5 `ruff format --check .` | pass | `578 files already formatted` |
| V5 `pytest -m "not integration"` | pass | `2549 passed, 2 skipped, 6 deselected` |
| V5 `stenographer --help` | pass | exit 0; `stenographer live --help` also exit 0 |
| No mic, recording, `live`/`run`, model download, integration tests, push of dev/main, PR, or workflow | pass | None run by the verifier |

Pilot tests use fake services; real recording, Files jobs, and the quit-saves
path on a live session are left to real-machine acceptance.

## Verdict

Pass. Every item passes.
