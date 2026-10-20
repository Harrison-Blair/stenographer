# VERIFIED — 45-ci-fix

Verifier run on 2026-10-19 at `3f0eedf` (fix commit `fb6605e`, base `fcc4867`).
The worktree had no `.venv`, so the verifier created a gitignored `.venv` in
the worktree with `python3 -m venv .venv` and `pip install -e '.[dev]'`
(Python 3.14.8, pytest 9.1.1, ruff 0.17.1, numpy 2.5.4, PyYAML 6.0.3).
Each item was re-run with the commands in `V<n>.md`.

| Item | Result | Observation |
| --- | --- | --- |
| V1 red: new test on base `fcc4867` (temporary worktree, `PYTHONPATH=src`) | pass | `1 failed`, exit 1. `ModuleNotFoundError: import of numpy halted; None in sys.modules` from `system_audio.py` line 9 |
| V1 green: `pytest tests/cli/test_entry.py::test_cli_help_does_not_import_numpy` | pass | `1 passed`, exit 0 |
| V1 code: numpy only under `TYPE_CHECKING`, alias uses string annotation | pass | Diff of `system_audio.py` matches. No behaviour change |
| V2 fresh venv `pip install --no-deps -e .` + `scripts/check-completions.sh` | pass | `completion checks passed: bash`, exit 0. zsh and fish skipped (not installed). No other runtime-dependency import blocked startup |
| V3 `pytest tests/lib/live/test_session_writer.py` | pass | `8 passed`. Diff shows only the 5 mode assertions gated by `os.name == "posix"`; naming, content, audio, rename assertions still run everywhere. Linux run unchanged |
| V4 PipeWire routing test | pass | `1 passed` on Linux. `skipif(sys.platform != "linux")` matches existing style (`tests/lib/platform/test_resource_probe.py`). `rg` over `tests/lib/live` finds no other test that drives `LinuxSystemAudioCapture` with fake executables |
| V5 refine parametrized tests | pass | `18 passed`. 7 and 4 `ids=` match parameter counts; 50,000-character case kept (`long-text-50000`) |
| V5 suite node-ID scan | pass | `collected=2554 nodeids_over_1000=0`, longest node ID 633 characters. (First attempt added `-q`, which conflicts with `-p no:terminal`; re-run without it as in V5.md) |
| V6 workflow YAML | pass | Both load with `yaml.safe_load`. `test.yml`: push dev, pull_request main, workflow_dispatch kept; concurrency `${{ github.workflow }}-${{ github.ref }}`. `native.yml`: push dev, pull_request dev/main, workflow_dispatch kept; no concurrency group. Only 2 lines added per file. `actionlint` not installed |
| V7 `ruff check .` | pass | `All checks passed!` |
| V7 `ruff format --check .` | pass | `575 files already formatted` |
| V7 `pytest -m "not integration"` | pass | `2546 passed, 2 skipped, 6 deselected`, exit 0 (skips: absent public audio clips in `tmp/live_audio`) |
| V7 `stenographer --help` | pass | exit 0, usage printed |
| AC4 no mic, live/run, integration, push, PR, or workflow | pass | None run by the verifier. Branch has `fb6605e` and `3f0eedf` on top of `fcc4867` |

Windows behaviour of R2–R4 is proven only by CI after landing (AC2); not
verified here.

## Verdict

Pass. Every item passes.
