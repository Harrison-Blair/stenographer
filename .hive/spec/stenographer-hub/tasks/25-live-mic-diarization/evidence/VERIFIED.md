# Verification: 25-live-mic-diarization

Verdict: **PASS**. Verifier: `t25-verifier-2`.
Source: `7fdcff6`. Feature base: `f5a0fc8`. Previous failing source: `b9a26e1`.
This report replaces the previous verdict. Git retains the previous report.

## Items

| Item | Result | Independent result |
| --- | --- | --- |
| V1: config default, load, validation, template, preservation, Config editor | pass | Config and hub tests pass. The base fails preservation and editor tests and cannot import the new LiveConfig model. |
| V2: parser, precedence, hub setting, completions | pass | Both flags appear in help. Parser, override, and hub forwarding tests pass. Bash completions pass. |
| V3: mic Room labels on, You labels off | pass | Synthetic phrases pass through the real session with fake external dependencies. Enabled mic phrases get room IDs and labels. Disabled mic phrases retain You. |
| V4: mic and system separation | pass | Separate trackers, distinct ID prefixes, and separate batch clustering pass. Clustering thresholds have no changes. |
| V5: stop relabel, skip, progress, failure handling | pass | Stop and skip tests pass. The new progress regression fails on b9a26e1 and passes on 7fdcff6. The independent real-relabel probe passes with the option off and on. |
| V6: room rename | pass | Tracker, session, and hub rename tests pass. Fresh standalone and hub renders list Room 1 and Room 2. |
| V7: session metadata and Sessions re-diarize | pass | Tests pass for flag persistence through revisions, old sessions, and separate mic/system relabeling. Source inspection confirms metadata is written during session construction. |
| V8: visual evidence and plain-text states | pass | Fresh before/after SVG, text, and PNG captures cover hub Live mixed/split, hub rename, Config, Config search, standalone Live, and standalone rename. |
| V9: repository gate and help | pass | Ruff check and format check pass. Full tests: 2723 passed, 2 skipped, 6 deselected. Root and live help exit 0. |
| V10: previous verification findings | pass | Combined progress remains monotonic with one total. Usage documentation now gives the setting, default, labels, flags, and hub behavior. |
| Requirement 7: documentation | pass | README, docs/live.md, docs/hub.md, docs/usage.md, and site/index.html cover the setting. The live guide states phrase boundaries, similarity limits, and system leakage into the microphone. |

## Independent runs

The worktree had no `.venv`. A temporary symlink selected the existing primary Python environment.
Textual 8.2.8 and its dependencies were installed only into a scratch target.
No package changed in the primary environment. `PYTHONPATH` selected this worktree's source and that target.

Commands from the worktree root:

```sh
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest -m "not integration"
.venv/bin/stenographer --help
scripts/check-completions.sh
.venv/bin/stenographer live --help
```

All commands exit 0. Ruff reports `All checks passed!` and `754 files already formatted`.
Pytest reports `2723 passed, 2 skipped, 6 deselected in 155.67s`.
The skips require an absent Silero model and absent public speaker clips.
Fish and Zsh are unavailable; their completion checks skip. Bash passes.
The live help command shows `--diarize-mic` and `--no-diarize-mic`; it starts no capture.
Full output: `reverify-runs/gate.log`.

For independent red and green runs, I ran this selection unchanged:

```sh
.venv/bin/pytest -v --continue-on-collection-errors -m 'not integration' \
  tests/lib/config tests/cli/hub/test_config.py tests/cli/hub/test_handler.py \
  tests/cli/hub/test_live_view.py tests/cli/hub/test_session_jobs.py \
  tests/cli/live/test_parser.py tests/cli/live/test_handler.py \
  tests/lib/live/test_live_session.py tests/lib/live/test_relabel.py \
  tests/lib/live/test_speaker_tracker.py tests/lib/sessions/test_store.py
```

Red uses source from `git archive f5a0fc8 src` through `PYTHONPATH`.
Result: **25 failed, 112 passed, 1 skipped, 1 collection error**.
The failures show absent feature options, room IDs, metadata, forwarding, and editor behavior.
The collection error is the absent LiveConfig import. Thus this base run does not provide
individual red assertions for the model tests. Existing compatibility guards can pass at base.
Green uses task source: **221 passed, 1 skipped**.
Logs: `reverify-runs/red.log` and `reverify-runs/green.log`.

The progress regression also ran against source from `git archive b9a26e1 src`:

```sh
.venv/bin/pytest tests/lib/live/test_live_session.py::test_stop_relabel_progress_counts_once_across_system_and_mic
```

Red: **1 failed**. Expected total `{3}`; observed totals `{1, 2}`.
The same test passes in both the task green selection and the full gate.
Log: `reverify-runs/progress-red.log`.

I also ran the independent probe with real batch relabeling:

```sh
DIARIZE_MIC=0 .venv/bin/python .hive/spec/stenographer-hub/tasks/25-live-mic-diarization/evidence/check_progress.py
DIARIZE_MIC=1 .venv/bin/python .hive/spec/stenographer-hub/tasks/25-live-mic-diarization/evidence/check_progress.py
```

Both exit 0. Off reports `0/1, 1/1`. On reports `0/3, 1/3, 1/3, 3/3`.
The total no longer resets between sources.
Logs: `reverify-runs/progress-0.log` and `reverify-runs/progress-1.log`.

## Visual check

The brief's user waiver replaces approved-board comparison with independent captures.
No approved board exists. `reverify-renders/` contains fresh before/after captures
from base and task source at 150 columns by 36 rows. All inputs are synthetic.
The task Config capture enables mic diarization. Synthetic session lines supply room speakers;
the tests above verify that the real session produces these labels.
Text files contain compositor text with no colour codes.
Firefox converted each pilot `save_screenshot()` SVG to PNG with a new scratch profile
and a window size of 1850 by 950. `rsvg-convert` is unavailable.
I inspected the PNGs and checked the plain text.

| Board element | state without colour | Result | Cause or decision |
| --- | --- | --- | --- |
| Hub mixed mic labels | You before; Room 1 and Room 2 after | overridden | Task waiver; separate speakers have distinct words. |
| Hub split mic column | MIC, Room 1, Room 2 | overridden | Task waiver; source caption and timestamps remain readable. |
| System labels and column | SYSTEM, Speaker 1 | matches | Labels and source separation remain unchanged. |
| Speaker count | 1 speaker before; 3 speakers after | overridden | Task waiver; count includes both room speakers. |
| Recording and source controls | REC, MIC on, SYSTEM on, dBFS | matches | Each state has words or numbers. |
| Hub rename title | Rename system speaker before; Rename speaker after | overridden | Task waiver; dialog now covers both sources. |
| Hub rename choices | Speaker 1, Room 1, Room 2 | overridden | Task waiver; room choices are plain text. |
| Standalone transcript | Room 1, Room 2, Speaker 1 | overridden | Task waiver; labels change without a layout change. |
| Standalone rename title and choices | Rename speaker; Speaker 1, Room 1, Room 2 | overridden | Task waiver; all choices remain distinct without colour. |
| Config group list | live; selected marker ▶ | overridden | Task waiver; added group follows asr. |
| Config selected setting | diarize_mic on ●; Default: off | overridden | Task waiver; value, changed marker, and default are explicit. |
| Config file status | 0 unsaved changes | matches | State has plain text. |
| Engine status | queue 2, failed 1, CPU percentage | differs | Live CPU samples vary between captures; no layout or feature difference. |

The scratch standalone capture initially encountered a periodic refresh during teardown.
The capture script now pauses timers after the final screenshot, before teardown.
Final capture runs complete successfully. No application source changed for verification.

## Limits and cleanup

No microphone, native audio capture, model download, or integration test ran.
Real-machine speaker quality and native platform behavior remain for user acceptance.
Reinstallation was not authorized or performed. The manager can offer `scripts/reinstall.sh`.
Scratch source archives, Textual target, browser profile, capture script, and temporary `.venv`
symlink were removed after the results were recorded. Final evidence remains in this folder.
