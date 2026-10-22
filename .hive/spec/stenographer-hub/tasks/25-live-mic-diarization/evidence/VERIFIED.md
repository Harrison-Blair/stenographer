# Verification: 25-live-mic-diarization

Verdict: **FAIL**. Verifier: `t25-verifier-1`.
Source: `6e7e8ad`. Base: `f5a0fc8`.

## Items

| Item | Result | Independent result |
| --- | --- | --- |
| V1: config default, load, validation, preservation, Config editor | pass | Task tests pass. Base rejects the new model import and fails the preservation/editor assertions. |
| V2: parser, flag precedence, hub setting | pass | Task tests pass. Base fails flag and forwarding assertions. Bash completions pass. |
| V3: Room labels on, You labels off | pass | Task tests pass. Base rejects the new constructor options and metadata property. |
| V4: separate mic and system speakers | pass | Separate tracker IDs and separate batch passes pass. Base rejects the new option. |
| V5: stop relabel, skip, progress, failure handling | fail | Relabel and skip tests pass. The independent progress check fails. Progress reaches 1/1, then resets to 0/2. See below. |
| V6: rename room speakers | pass | Tracker, session, and hub rename tests pass. Independent standalone and hub captures list both room speakers. |
| V7: metadata and Sessions re-diarize | pass | Flag persistence, old sessions, and separate source relabel tests pass. |
| V8: independent visual evidence and plain-text states | pass | Before/after captures cover hub mixed/split Live, hub rename, Config, Config search, standalone Live, and standalone rename. |
| V9: required gate and help | pass | Ruff check and format check pass. Pytest reports 2722 passed, 2 skipped, 6 deselected. Root and live help exit 0. |
| Docs | fail | README, live guide, hub guide, and Pages explain the setting. The live guide states all three requested limits. Requirement 7 also names usage documentation when it lists config keys. Usage lists config keys but has no update for this setting. |

## Failure: session progress resets between sources

Requirement 3 requires stop-time relabeling to preserve progress behavior.
`src/stenographer/lib/live/live_session.py:356` starts with a combined total.
At line 364, each source passes its local progress directly to `_set_relabel_progress`.
That callback replaces the session progress at lines 389–391.

The independent check uses the real session and real batch relabel function.
Only audio capture, ASR, VAD, and embedding dependencies use synthetic test fixtures.
The check observes progress without replacing relabel behavior.

```sh
DIARIZE_MIC=0 .venv/bin/python .hive/spec/stenographer-hub/tasks/25-live-mic-diarization/evidence/check_progress.py
# exit 0: 0/1, 1/1

DIARIZE_MIC=1 .venv/bin/python .hive/spec/stenographer-hub/tasks/25-live-mic-diarization/evidence/check_progress.py
# exit 1:
# Relabeling speakers 0/1 · q to skip
# Relabeling speakers 1/1 · q to skip
# Relabeling speakers 0/2 · q to skip
# Relabeling speakers 2/2 · q to skip
# AssertionError: Progress resets after the first source is complete
```

Expected: progress must describe the whole operation, or explicitly identify each source pass.
It must not show completion before another unannounced pass begins.
The saved labels remain correct in this check. The defect affects the progress display.
Add a regression test for progress across both sources before repair.

## Documentation gap

Requirement 7 names `docs/usage.md` when it lists configuration keys.
That file lists keys in several TOML examples, including feedback, delivery, and analytics settings.
Its live section at lines 218–225 remains unchanged.
It does not mention `stenographer.live.diarize_mic` or either override flag.
The owning live guide contains the information. Add a brief usage entry or configuration example to meet the stated scope.

## Test commands and environment

The worktree had no `.venv`. A temporary symlink used the existing Python environment.
`PYTHONPATH` selected the worktree source and an isolated scratch install of Textual.
The primary environment lacks Textual. No packages changed in that environment.

For the red run, `git archive f5a0fc8 src` supplied the source through `PYTHONPATH`.
The current tests remained unchanged. Both runs used `pytest -v --continue-on-collection-errors -m 'not integration'`.
The selection covered the V1–V7 test names and these paths:

```text
tests/lib/config
tests/cli/hub/test_config.py
tests/cli/hub/test_handler.py
tests/cli/hub/test_live_view.py
tests/cli/hub/test_session_jobs.py
tests/cli/live/test_parser.py
tests/cli/live/test_handler.py
tests/lib/live/test_live_session.py
tests/lib/live/test_relabel.py
tests/lib/live/test_speaker_tracker.py
tests/lib/sessions/test_store.py
```

The selection also included existing regression guards.
Red: **24 failed, 98 passed, 1 skipped, 14 deselected, 1 collection error**.
Green: **206 passed, 1 skipped, 14 deselected**.
The red collection error is the absent `LiveConfig` import in the base source.
The model tests cannot run past that import at base. This limits the red evidence for those tests.
Existing compatibility guards can pass at base.

I independently ran these commands from the worktree root:

```sh
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest -m "not integration"
.venv/bin/stenographer --help
scripts/check-completions.sh
.venv/bin/stenographer live --help
```

Ruff: `All checks passed!`; `751 files already formatted`.
Pytest: `2722 passed, 2 skipped, 6 deselected in 152.26s`.
The skips require an absent Silero model and absent public speaker clips.
Bash completions pass. Fish and Zsh are unavailable, so their checks skip.
The live help command shows both new flags. It does not start capture.

Full outputs: `verifier-runs/{red,green,gate,progress-off,progress-on}.log`.
The independent probe is `check_progress.py` beside this report.

## Visual check

The task brief waives approved boards for this task.
Independent pilot captures use base source for `before-*` and task source for `after-*`.
The task captures enable mic diarization in the real session and in Config.
All capture inputs are synthetic. No microphone, model, or native audio capture ran.
Each capture has SVG, plain text, and PNG files in `verifier-renders/`.
Firefox converted the SVG captures to PNG with a new scratch profile.
I inspected the PNGs and their plain text.

| Board element | state without colour | Result | Cause or decision |
| --- | --- | --- | --- |
| Live mic labels, mixed view | `You` before; `Room 1`, `Room 2` after | overridden | The task waiver approves independent captures. The new labels identify separate speakers. |
| Live mic labels, split view | `MIC`, `Room 1`, `Room 2` | overridden | The same waiver applies. Columns and time order remain intact. |
| System label | `Speaker 1` | matches | The label and system accent remain unchanged. |
| Live speaker count | `1 speaker` before; `3 speakers` after | overridden | The count now includes the two room speakers. |
| Capture controls | `REC`, `MIC on`, `SYSTEM on`, dBFS values | matches | Words and numbers identify the states without colour. |
| Hub rename title | `Rename system speaker` before; `Rename speaker` after | overridden | The dialog now includes room speakers. |
| Hub rename choices | `Speaker 1`, `Room 1`, `Room 2` | overridden | Each choice has a distinct text label. |
| Standalone transcript | `Room 1`, `Room 2`, `Speaker 1` | overridden | Layout remains unchanged. Labels identify the sources. |
| Standalone rename title and choices | `Rename speaker`, `Speaker 1`, `Room 1`, `Room 2` | overridden | The standalone dialog includes room speakers. |
| Config group list | `live`, selected marker `▶` | overridden | The new group follows `asr`. Other groups retain their order. |
| Config value and help | `diarize_mic on ●`, `Default: off` | overridden | The value, default, and changed marker remain readable without colour. |
| Config unsaved status | `0 unsaved changes` | matches | The state uses plain text. |

No approved board exists for this task, so no board capture applies.
Real-machine speaker quality, microphone behavior, and native platform behavior remain unverified.
Reinstallation was not authorized or performed.
