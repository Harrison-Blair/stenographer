# VERIFIED — 34-live-tui

Verifier re-run on 2026-10-19 at commit 7b846ba. The worktree has no `.venv`.
Tools came from `/home/penguin/source/stenographer/.venv/bin` with
`PYTHONPATH=src`. `stenographer.__file__` resolved to this worktree's `src/`.

Red runs used a scratch worktree at the base `ab224d0` with only the new tests
applied. Mutation red runs applied the task's `src` diff there and changed one
line at a time. Each line was restored before the next change.

| Item | Result | Observation |
| --- | --- | --- |
| V1 LiveSession | pass | Red at base: `6 failed, 1 passed` (`ModuleNotFoundError: stenographer.lib.live.live_session`). The worker recorded `3 failed, 1 passed` with an earlier test count. Every coordinator test fails in both runs. Mutation (system `available()` result ignored): `test_unavailable_system_source_stays_off_and_exposes_the_reason` failed, 6 passed. Green: `7 passed`. |
| V2 CLI and registration | pass | Red at base: parser collection `ModuleNotFoundError: stenographer.cli.live`; handler `2 failed`; registry test `LookupError: no registered command named 'live'`; completion tests with base assets `3 failed, 12 passed` (bash, zsh, fish). Mutation (model check reversed): handler `2 failed`. Green: the change-specific set `48 passed`; completion `15 passed`. `--no-mic --no-system` → `error: argument --no-system: not allowed with argument --no-mic`. `cli/live/` has no lock or `startup` reference. |
| V3 Textual app | pass | Red at base: collection `ModuleNotFoundError: stenographer.cli.live`. Mutation (`action_stop` calls `stop()` synchronously): `test_stop_does_not_block_the_ui_while_transcript_callbacks_finish` failed, 2 passed. Green: `3 passed`. |
| V4 R4 and regression suite | pass | Change-specific set: `48 passed`. Full suite `pytest -m "not integration"`: `2538 passed, 2 skipped, 6 deselected`. The skips need live VAD model files or public speaker clips. |
| V5 Gate and acceptance checks | pass | `ruff check .`: `All checks passed!`. `ruff format --check .`: `588 files already formatted`. `stenographer --help` lists `live`. `stenographer live --help` lists `--mic`, `--no-mic`, `--system`, `--no-system`, `--device DEV`. `scripts/check-completions.sh`: bash passed; zsh and fish skipped (shells not installed). With isolated XDG dirs and HOME: exit 1, 0 bytes on stdout, stderr names `stenographer model download --live`. |

No microphone, system audio capture, integration test, or real ASR child ran.
Acceptance check 3 (real audio, spec section 8) belongs to the manager and the
user after landing. This verification does not cover it.
