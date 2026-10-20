# Task: relabel-memory — bound memory of the default stop-pass relabel

| Item | Value |
| --- | --- |
| Tier | decent |
| Depends on | 59 (files-engine), which also edits `lib/live/relabel.py` |

## Overview

The default speaker relabel pass (`relabel_system_lines` with no
`speaker_count`, `lib/live/relabel.py`, landed in task 58) runs when a live
session stops, when a file job ends, and on a session re-diarize. Task 59's
probe (`.hive/spec/stenographer-hub/tasks/59-files-engine/evidence/V3.md`)
measured it on 9,000 synthetic 2.2 s phrases (about 5.6 h of dense speech):
316 s and 11.85 GiB peak RSS. An earlier probe measured 4.49 GiB. The
fixed-count path in the same file now does 9,000 phrases in 0.41 GiB and
0.7 s with a dense float32 matrix and no per-pair Python objects. A long
session on an 8-16 GB machine can run out of memory at stop. The audio is
saved first, so it loses the labels and the user waits minutes.

## Requirements

1. Make the default pass use bounded memory: at most a dense float32
   similarity matrix over the anchor phrases, no per-pair Python objects or
   heaps of tuples, and per-row best tracking or an equivalent. Target for
   9,000 long phrases: peak RSS at or under 1 GiB and time under 30 s on
   this machine.
2. Results must not change: for the same input, the output labels and
   speaker ids must be identical to the current code. Show this with a
   comparison on synthetic inputs (several seeds, mixed long and short
   phrases, minor voices, residue) and with all existing relabel tests.
   Where an exact tie is ordered differently, state it and keep the current
   order.
3. The real-audio check (user consent granted 2026-10-20 for this task only): rerun `scripts/relabel_audio.py` on the consented
   recording `/home/penguin/source/stenographer/system-audio-20261018-134825.wav`
   and show the same output as task 58 (4 clusters, 4 labels, Speaker 1-4
   = 3222.3 / 5174.5 / 4572.4 / 1700.9 s, 360 short phrases). Print counts
   and talk times only; write no audio or text. Read it by that absolute
   path; never copy or commit it.
4. Evidence: a probe table (phrases 2,000 and 9,000; time; peak RSS) before
   and after, measured in fresh processes.

## Common rules

- Goal: `.hive/tmp/coordinator/goal-stenographer-hub.md` in the hive home
  (decisions 1 to 15). Design boards: `.hive/tmp/coordinator/designs/stenographer/`.
  Plan review: `.hive/tmp/reports/plan-review-stenographer.md`. Read the parts
  that apply. The boards set layout and content, not exact colours or sizes.
  The board `Config.dc.html` shows two profile columns. That is out of date
  (decision 15): one column of ASR settings.
- Grant: `grants.md 2026-10-19 stenographer hub tasks` (merge to `dev` only).
- Follow the repository `AGENTS.md`. Linux only. Keep the headless core: the
  daemon and every existing subcommand keep their behaviour (decision 2).
- Evidence in `evidence/<task-id>/`, committed with `git add -f`. Never add
  evidence paths to `.gitignore` or `pyproject.toml`. Never put transcript
  text or audio in evidence, logs or history. Counts and timings are fine.
- No tautological tests. Mock only external dependencies. Each new
  regression test fails at base (show it), then passes.
- Do not open the microphone, capture audio, run `live` or `run`, download a
  model, or run integration tests. The user does those on the real machine.
- Never signal a process or close a tab, pane or workspace that you did not start; compare with the pid and pane ID recorded at start. Never work in workspace wBC (the hive session).
- Do not push `dev` or `main`, open a pull request, or run a workflow.
- Gate before `hive task complete`, with zero failures:

  ```sh
  .venv/bin/ruff check .
  .venv/bin/ruff format --check .
  .venv/bin/pytest -m "not integration"
  .venv/bin/stenographer --help
  ```
