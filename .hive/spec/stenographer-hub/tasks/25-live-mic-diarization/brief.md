# Task: live-mic-diarization — optional speaker diarization for the microphone

| Item | Value |
| --- | --- |
| Tier | strong |
| Depends on | none |

## Overview

Use case: one microphone in a room with more than one person; the transcript
should separate the speakers. Today `LiveSession._transcribe_phrase`
(`src/stenographer/lib/live/live_session.py`) gives every mic phrase
`speaker_id="you"`, `label="You"`. Only system phrases go through the
`SpeakerTracker` (online assignment) and `relabel_system_lines`
(`lib/live/relabel.py`, batch clustering at stop, `_relabel_saved_session`).
Sessions `d` re-diarize (`cli/hub/session_jobs.py`) also covers system lines only.

## Decisions (user, 2026-10-21)

1. Method: a second, mic-only `SpeakerTracker` (same speaker model, no new
   dependency), plus the existing batch relabel at stop applied to mic lines
   separately from system lines. Mic and system speakers are never clustered together.
2. Setting: config key `stenographer.live.diarize_mic` (bool), plus
   `stenographer live --diarize-mic` / `--no-diarize-mic` (flag overrides config).
   The hub Live section uses the config value. No mid-session toggle.
3. Default: off. With it off, behaviour is byte-for-byte unchanged (mic = `You`).
4. Labels: mic speakers are `Room 1`, `Room 2`, ... (distinct from system
   `Speaker N`), renameable with `r` in live and in the hub and Sessions.
   Speaker IDs must not collide with system IDs (e.g. `room-1` vs `speaker-1`).
5. Re-diarize: a flag in the session metadata (`session.json`, already read by
   `lib/sessions/reader.py`) records whether the session was recorded with mic
   diarization. Sessions `d` relabels mic lines only when that flag is set;
   old sessions without the flag behave as today.

## Design

No approved board. User waiver, 2026-10-21 (through the coordinator), for
tasks 24 and 25 only: this change does not alter a layout, so the
approved-board comparison is waived. The verifier's independent before and
after renders of each changed screen (pilot `save_screenshot()` SVG, text and
PNG, synthetic data only) count as the visual approval. Keep those renders in
the evidence. The plain-text check still applies: each state must have a glyph or
word and must not rely on colour alone. Future UI tasks still need an approved board.

## Requirements

1. Config: add a `live` table to the config model with `diarize_mic = false`,
   with validation, the default config template, and the hub Config board
   (`config_view.py` already lists a `live` group). Existing configs without the
   table load unchanged; saves go through the existing preservation layer.
2. Parser/handler for `--diarize-mic/--no-diarize-mic`; update completions
   (`scripts/check-completions.sh` must pass).
3. LiveSession: with the setting on, mic phrases are embedded and assigned by
   the mic tracker; `relabel` at stop covers mic lines too (respecting the
   existing skip with `q`, progress, and failure handling). The relabel
   clustering thresholds stay as they are. Generalise `relabel_system_lines` only
   as far as needed for the `Room N` label prefix; keep system behaviour identical.
4. Rename (`r`) lists room speakers when present, in the standalone live app
   and the hub.
5. Session metadata flag written at session start; Sessions re-diarize honours it.
6. Failing-first tests (inject a fake embedding/tracker at the existing seams;
   no microphone, no model): mic phrases labeled `Room N` when on and `You`
   when off; mic and system speakers stay separate; stop relabel revises mic
   labels; rename of a room speaker; config default/load/round-trip; CLI flag
   precedence; re-diarize respects the metadata flag and old sessions.
7. Docs: `docs/live.md` (setting, labels, limits: labels are per VAD phrase, so a
   speaker change without a pause stays in one phrase; similarity estimates only;
   system audio leaking into the mic can appear as a room speaker), `docs/hub.md`
   (Live, Sessions, Config), `docs/usage.md` config reference if it lists config keys,
   README, and `site/`.
8. Evidence: the failing-first runs, and a hub Live render (pilot SVG plus text,
   synthetic lines) showing `Room 1`/`Room 2` with the setting on.

Evidence folder: `.hive/spec/stenographer-hub/tasks/25-live-mic-diarization/evidence/`.
## Common rules

- User decisions, 2026-10-21 (through the coordinator): the decisions in this
  brief are final. They extend the hub spec `.hive/spec/stenographer-hub/README.md`.
- Grant: `grants.md 2026-10-21 stenographer delivery on dev` (merge to `dev` only, never `main`).
- Follow the repository `AGENTS.md`. Linux only. Keep the headless core: the
  daemon and every existing subcommand keep their behaviour.
- User-facing changes update README.md, the owning docs, and the Pages site
  (`site/`). The primary checkout has uncommitted user edits in README.md,
  docs/usage.md, pyproject.toml and site/index.html. Never touch that checkout;
  work only in your task worktree.
- Evidence in the evidence folder named below, committed with `git add -f`.
  Never add evidence paths to `.gitignore` or `pyproject.toml`. Never put
  transcript text or audio in evidence, logs or history. Counts and timings are fine.
- No tautological tests. Mock only external dependencies. Each new
  regression test fails at base (show it in evidence), then passes.
- Do not open the microphone, capture audio, run `live` or `run`, download a
  model, or run integration tests. The user does those on the real machine.
- Never signal a process or close a tab, pane or workspace that you did not
  start. Never work in workspace wBC (the hive session).
- Do not push `dev` or `main`, open a pull request, or run a workflow.
- Commits: conventional commits, no attribution or Co-Authored-By trailers.
- Gate before `hive task complete`, with zero failures:

  ```sh
  .venv/bin/ruff check .
  .venv/bin/ruff format --check .
  .venv/bin/pytest -m "not integration"
  .venv/bin/stenographer --help
  ```
