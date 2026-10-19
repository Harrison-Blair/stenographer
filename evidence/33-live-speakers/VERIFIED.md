# 33-live-speakers verification

| Item | Value |
| --- | --- |
| Task | 33-live-speakers |
| Commit verified | 4b40477 |
| Date | 2026-10-19 |
| Agent | verifier, claude-code, claude-opus-5-5 |

## Setup

The worktree had no `.venv`. The verifier created one with
`python3 -m venv .venv && .venv/bin/pip install -e '.[dev]' build` (Python
3.14.8; sherpa-onnx 1.13.8 comes from the project dependencies). The three
public `csukuangfj/sr-data` `test/3d-speaker` clips were downloaded into the
ignored `tmp/live_audio/`, and the model came from
`XDG_DATA_HOME="$PWD/tmp/xdg-data" .venv/bin/stenographer model download --live`.

## Results

| Item | Check | Result |
| --- | --- | --- |
| V1 | Pure clustering tests: green run 4/4 pass. Independent red runs by mutation: "never join" fails the join and mean tests; "no mean update" fails the mean test; "reuse IDs" fails the new-speaker and no-reuse tests. | pass |
| V2 | Tracker and label tests: green run 3/3 pass. Red runs: no empty-name refusal, no strip, and a wrong default label each fail the matching test. | pass |
| V3 | Real-model test with the public clips: green run passes (not skipped). Red runs: "always speaker-1" fails `third != first`; "always new" fails `first == second`. | pass |
| V4 | Gate: `ruff check .` exit 0; `ruff format --check .` exit 0 (568 files); `pytest -m "not integration"` 2513 passed, 5 deselected, 0 skipped, exit 0; `stenographer --help` exit 0. Git and Hatch allowlists match (131 rules). | pass |

## Commands

```sh
PYTHONPATH="$PWD/src" .venv/bin/pytest -q tests/lib/live/test_speaker_tracker.py
# 8 passed in 0.23s
.venv/bin/ruff check .                 # All checks passed! / exit 0
.venv/bin/ruff format --check .        # 568 files already formatted / exit 0
.venv/bin/pytest -q -m "not integration"   # 2513 passed, 5 deselected / exit 0
.venv/bin/stenographer --help          # exit 0
```

Each mutation ran in a `git archive HEAD` copy in the scratchpad, with one
string replaced, running `tests/lib/live/test_speaker_tracker.py`. The task
worktree was not changed.

## Notes (not failures)

- Mutation "remove the `you` refusal" survives. `rename("you", ...)` still
  raises `ValueError` from the unknown-ID check, so the refusal still holds
  and the mutant is equivalent. A direct check gave `label("you") == "You"`
  and the message "The microphone source cannot be renamed".
- Mutation "`>= threshold` to `> threshold + 0.05`" survives. No test hits
  the exact threshold boundary. The brief does not ask for a boundary test.
