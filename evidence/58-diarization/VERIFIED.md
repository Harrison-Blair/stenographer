# VERIFIED — 58-diarization

Independent verifier run on 2026-10-20 at `da74e74`. `.venv` was a temporary
symlink to `/home/penguin/source/stenographer/.venv`; the CLI and tests loaded
this worktree's `src/`. Red runs used a detached base worktree at the merge
base with `dev`, with the task's `tests/` copied over.

| Item | Result | Observation |
| --- | --- | --- |
| V1 live and batch clustering (red/green) | pass | Base: `test_relabel.py` fails at collection; the 3 new short-phrase tests in `test_speaker_tracker.py` fail. Head: all pass. The 3-clip real-model test is kept and skips (public clips absent here too). |
| V2 stop pass, revisions, controls (red/green) | pass | Base: the 3 new `test_live_session.py` stop tests, `test_app.py::test_second_q_skips_relabel_and_stop_progress_is_visible` and the handler test fail (8 failed, 27 passed). Head: pass. |
| V3 real-audio check | pass (evidence consistent; not rerun) | Recorded output: 457 labels at base, 4 after the stop pass, 360 phrases under 1.2 s. Not rerun (about 5.6 h of audio). See finding F1: the script counts by label name, so it cannot show two clusters that share one label. |
| V4 gate | pass | `ruff check .` all passed; `ruff format --check .` 590 files formatted; `pytest -m "not integration"` 2564 passed, 2 skipped, 6 deselected; `stenographer --help` prints usage. |
| Requirement 2: rename mapping | **fail** | See F1. |

## Findings

**F1 (fails requirement 2). Two batch clusters can get the same label.**
`relabel_system_lines` (`src/stenographer/lib/live/relabel.py`, final loop)
gives each cluster the old label with the most speech time, with no check for
collisions. Synthetic probe: live labelled voice A (10 s) and voice B (5 s)
both "Speaker 1", plus 2 s of B as "Speaker 2". The batch pass split the
voices correctly (`speaker-1`, `speaker-2`), and labelled **both** clusters
"Speaker 1". The user sees one speaker where the batch found two. If the user
had renamed "Speaker 1" to a name, that name now also covers a second voice,
which is what the brief's mapping should prevent ("a name the user gave stays on the
same voice"). `scripts/relabel_audio.py` groups talk time by `line.label`, so
the "Labels: 4" in V3 could hide more than 4 clusters. Each old label must go
to at most one cluster; other clusters need a fresh label.

**F2 (manager note 1; not a brief failure by itself).** With no renames, the
pass keeps live numbers. In V3 a 4-speaker session shows "Speaker 11",
"Speaker 172", "Speaker 2", "Speaker 22". Synthetic probe: clusters dominated by
live "Speaker 7" and "Speaker 9" keep those names. The brief's mapping rule,
read literally, gives this result, so it does not fail the brief alone. A user
would expect unnamed labels renumbered 1..N in speech order, with only renamed
labels kept. Fix it together with F1, because both are in the same
label-assignment loop. The pass currently cannot tell a rename from a default
label. The tracker's rename map or the default `Speaker N` pattern can supply
that.

**Manager note 3: nonblocking stop.** Kept. `action_stop` starts
`_finish_stop` as an `asyncio` task and returns. `_finish_stop` runs
`session.stop` in `asyncio.to_thread`. A second `q` calls `skip_relabel()`.
The head test `test_second_q_skips_relabel_and_stop_progress_is_visible`
covers this. Overlap with task 72 (`72-tui-input-first`): that worktree has
no code changes yet. This task changes `action_stop`, adds `_finish_stop`,
`_stop_requested`, `_stop_task`, a longer key-hints line, and the relabel
status in `_refresh_status` in `src/stenographer/cli/live/app.py`. Task 72
will touch the same key handling and hints.
