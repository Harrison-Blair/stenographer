# Stenographer hub

This file is the design authority for the hub goal, confirmed by the user on
2026-10-19. Start after v0.14.0 is published. Linux is the supported platform.

## Goal and decisions

1. In a TTY, bare `stenographer` opens the hub. Without a TTY, it prints help.
2. Keep the headless core. The daemon and every existing subcommand keep
   their behavior, including `stenographer live` and its flags.
3. Use direction B: bordered panels, dark background, monospace font.
4. Show six sidebar sections. Keys `1` to `6` select Live, Files, Sessions,
   Config, Setup, and Doctor, in that order.
5. **Live:** show REC, mic, and system panels with meters. `m` and `s` toggle
   sources. Show a mixed transcript with speaker chips by default; `v` shows
   time-ordered MIC and SYSTEM columns. Keep the existing live behavior.
6. **Files:** browse and queue files; set diarization, speaker count, refine,
   output format, and output folder. Show job progress and a result preview.
7. **Sessions:** list saved sessions. Show speaker talk time, mic and system
   activity, and the transcript. Support playback, re-diarization,
   re-transcription, rename, export, and delete.
8. **Config:** edit settings by group. Save through the config preservation
   layer with a timestamped `config.toml.bak-<time>` backup. Show one column
   of ASR settings; do not add profiles.
9. **Setup:** provide six steps: input access, microphone, hotkey, models,
   sounds, and system service. Keep `stenographer setup` behavior.
10. **Doctor:** show existing checks, grouped with details and fixes. Add new
    checks as warnings. Show recent warnings from the log without transcript
    text.
11. **Diarization:** short live phrases must not create a new speaker each
    time. The observed session had six labels for two to three voices. At stop,
    run one full re-label pass over the session and save the labels.
12. **Transcription:** benchmark models, beam size, recent-line context, and
    hotwords before changing defaults. Measure accuracy and dictation latency.
    Use one ASR setting set for dictation, live, and Files; the user picks
    defaults from the results.
13. Open the hub on Live. Start recording only when the user presses space.
    Changing sections does not stop recording. Files jobs run one at a time
    in the background. Ask to confirm quit while recording, then save the
    session. Keep the Files-job quit prompt.
14. Drop Windows support. Keep the Platform protocol. Do this before the hub
    tasks.
15. Use one set of ASR settings across the tool. The two profile columns on
    `Config.dc.html` are out of date.

## Accepted assumptions

- Files reads supported formats with `soundfile`. It reads M4A and AAC through
  the system `ffmpeg` binary and a pipe. Do not use PyAV, which bundles FFmpeg
  libraries. The system binary is present on the user's machine. Report it if
  missing; Doctor warns when it is missing.
- Recent-line context is new. Ship it only if the user chooses it from the
  benchmark results.
- The user approved one download of the benchmark WER corpus, about 1.08 GB.
- The user approved use of `system-audio-20261018-134825.wav` (5.65 hours,
  four speakers) for the benchmark and diarization task. Never commit the
  recording or its transcript text.
- `stenographer live` keeps its flags.
- Config backups use the timestamped `config.toml.bak-<time>` form.
- New Doctor checks are warnings.
- Session playback uses `pw-play`.

## Task plan

Statuses reflect the plan confirmed for this goal: 54, 57, and 60 landed; 55
and 58 running; all other numbered tasks waiting.

| ID | Task | Depends on | Status |
| --- | --- | --- | --- |
| 54 | Remove Windows support | — | landed |
| 55 | ASR bench | 54 | running |
| 56 | Apply ASR defaults | 55 and user's choice | waiting |
| 57 | Sessions store | 54 | landed |
| 58 | Diarization | 57 | running |
| 59 | Files engine | 57, 58 | waiting |
| 60 | Hub shell | 54 | landed |
| 61 | Hub Live | 58, 60 | waiting |
| 62 | Hub Files | 59, 60 | waiting |
| 63 | Hub Sessions | 57, 58, 60 | waiting |
| 64 | Hub Config | 56, 60 | waiting |
| 65 | Hub Setup and Doctor | 56, 60, 64 | waiting |
| 66 | Hub docs and acceptance | 61, 62, 63, 65 | waiting |
| 72 | Hub start, save, and cancel work in workers; `q` and `ctrl+c` confirm quit | 60, 68 | in progress |

Tasks before this spec keep evidence in `evidence/<task-id>/`. New feature
tasks keep evidence in `.hive/spec/stenographer-hub/tasks/<id>/`.

## Design boards

The boards remain in the hive home at
`/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/`.
Do not copy them into this repository.
