<!--
SPDX-License-Identifier: GPL-3.0-or-later
-->

# 00 — Overview

> Foundation document. Read this first. Every other spec doc in this folder
> refers back to the terms and component boundaries defined here.

## Goal

Specify `stenographer`: a Wayland-only, local-only push-to-talk / toggle
dictation daemon. A user presses a configurable global hotkey, speaks, and the
recognized text is injected at the cursor and copied to the Wayland
clipboard. A short audio cue confirms that recording has started and stopped.

This document fixes the **shape** of the system. Component behaviour is
specified in `01-hotkey.md` through `10-packaging.md`.

## Glossary

| Term                | Definition                                                                                   |
|---------------------|----------------------------------------------------------------------------------------------|
| `Utterance`         | One mic recording, from hotkey-press to hotkey-release (or toggle stop).                     |
| `Mode`              | Either `PTT` (press-and-hold) or `Toggle` (press-to-start, press-to-stop).                   |
| `Hotkey`            | A single key or chord; the user-configurable trigger. Default: right Ctrl.                   |
| `Session`           | A `Utterance` plus its metadata (start time, mode, samples, transcript).                     |
| `Cue`               | A short audio file played at a state transition.                                            |
| `Capabilities`      | The set of optional features detected at startup (`wtype`, `wl-copy`, `pw-play`, `paplay`). |
| `Daemon`            | The long-running process started by `stenographer run`.                                      |
| `One-shot`          | A short-lived process started by `stenographer transcribe FILE` or `stenographer dictate`.   |
| `Worker`            | The background thread that runs the ASR model.                                              |
| `Recorder`          | The background thread that streams mic audio into a per-utterance buffer.                   |
| `Injector`          | The component that synthesises keystrokes via `wtype`.                                       |
| `Clipboard Manager` | The component that writes to / reads from the Wayland clipboard via `wl-copy` / `wl-paste`.  |

## Components

```
                +-------------------+
                |    HotkeyListener |  (python-evdev, /dev/input/event*)
                +---------+---------+
                          | keydown / keyup
                          v
                +-------------------+
                |      Session      |  (orchestrator, main thread)
                +--+-----+-----+----+
                   |     |     |
   start Recorder  |     |     |  fire start cue
                   v     v     v
        +---------+ +----+----+ +-----------+
        | Recorder| |  Cue   | |  ...      |
        | thread  | | player | |           |
        +---------+ +---------+ +-----------+
                   |
   audio buffer    |
                   v
        +---------+      +----------------+
        |  Worker |----->|  Transcript    |
        |  thread |      |  (faster-      |
        +---------+      |   whisper)     |
                          +-------+--------+
                                  |
                          +-------v--------+
                          |   Injector     |  -> wtype -> focused window
                          +----------------+
                                  |
                          +-------v--------+
                          | Clipboard Mgr  |  -> wl-copy
                          +----------------+
```

| Component        | Lives in module                       | Spec doc                |
|------------------|---------------------------------------|-------------------------|
| HotkeyListener   | `stenographer.hotkey`                 | `01-hotkey.md`          |
| Session          | `stenographer.session`                | (this doc, `08-process-model.md`) |
| Recorder         | `stenographer.audio.capture`          | `02-audio-capture.md`   |
| Worker           | `stenographer.asr`                    | `03-transcription.md`   |
| Cue player       | `stenographer.audio.feedback`         | `04-audio-feedback.md`  |
| Injector         | `stenographer.output.inject`          | `05-text-output.md`     |
| Clipboard Mgr    | `stenographer.output.clipboard`       | `06-clipboard.md`       |
| Config loader    | `stenographer.config`                 | `07-configuration.md`   |
| Process entry    | `stenographer.cli`                    | `08-process-model.md`   |
| Error policy     | `stenographer.errors`                 | `09-error-handling.md`  |
| Packaging        | `pyproject.toml`, `assets/`, `units/` | `10-packaging.md`       |

## Data flow per utterance

1. `HotkeyListener` emits `keydown` / `keyup` events to `Session`.
2. `Session` decides the `Mode` (see `01-hotkey.md` state machine).
3. `Session` starts the `Recorder` (opens a `sounddevice.InputStream`) and asks
   the `Cue player` to fire the start cue.
4. Audio frames accumulate in a per-utterance `numpy.ndarray` of shape
   `(n_samples, 1)` and dtype `float32`.
5. On stop, `Session` hands the buffer to the `Worker`.
6. `Worker` runs faster-whisper and returns a `Transcript` (a `str`).
7. `Session` asks the `Injector` to type the transcript, and the
   `Clipboard Mgr` to copy it.
8. `Session` fires the stop cue and returns to idle.

## Lifecycle (daemon)

```
boot -> capability probe -> config load -> hotkey device probe
     -> register hotkey -> IDLE
IDLE -> (keydown) RECORDING
RECORDING -> (stop) TRANSCRIBING
TRANSCRIBING -> (output) IDLE
(any) -> (SIGINT/SIGTERM) drain -> exit 0
```

## Capability probe (run once at startup)

The following are probed; missing items downgrade the daemon gracefully
(see `09-error-handling.md`):

- `wtype` on `PATH` -> enables cursor injection.
- `wl-copy` on `PATH` -> enables clipboard writes.
- `pw-play` on `PATH` -> preferred cue player; else fall back to `paplay`.
- `paplay` on `PATH` -> fallback cue player.
- User in `input` group (or has uaccess on the keyboard device) -> enables
  hotkey capture. If not, daemon logs and exits with code 78
  (`EX_CONFIG`).
- Default mic input device present (via `sounddevice.query_devices`) -> enables
  recording. If not, daemon exits with code 78.
- ASR model present at the resolved path (see `03-transcription.md`) ->
  enables dictation. If not, daemon logs the `stenographer model download`
  command and exits 78.

## Build order (dependency DAG for subagents)

Read this section before spawning implementer subagents. Tier rows are run
in parallel within a tier; tiers run in order.

| Tier | Docs                          | Notes                                                                       |
|------|-------------------------------|-----------------------------------------------------------------------------|
| 0    | `00-overview.md`              | Reference for all other tiers. Written first.                               |
| 1    | `07-configuration.md`         | Defines the config schema that all component docs reference.                |
| 1    | `10-packaging.md`             | Declares system + Python deps each component doc cites.                     |
| 1    | `09-error-handling.md`        | Fixes the degradation policy every component doc must honour.               |
| 2    | `02-audio-capture.md`         | Recorder thread.                                                             |
| 2    | `03-transcription.md`         | ASR Worker.                                                                  |
| 2    | `04-audio-feedback.md`        | Cue player.                                                                  |
| 2    | `06-clipboard.md`             | Clipboard writes / reads.                                                    |
| 2    | `01-hotkey.md`                | Hotkey state machine.                                                        |
| 3    | `05-text-output.md`           | Depends on `06-clipboard.md` (fallback path).                                |
| 4    | `08-process-model.md`         | Wires everything together; depends on all of the above.                     |

Each component spec doc must contain a `## Dependencies` section that lists
which other spec docs it consumes (read before implementing) and which it
blocks (cannot start before this one is done).

## Out of scope (v1)

- X11 support.
- Cloud ASR (OpenAI Whisper API, Deepgram, etc.).
- Streaming / partial transcripts (one final transcript per utterance).
- Multiple simultaneous languages (English only; `language` is pinned).
- Live reloading of the config (`SIGHUP` is not handled; restart required).
- GUI / system-tray icon. The daemon is silent and headless.
- Push-to-talk and toggle as **separate** bindings (the hybrid logic
  arbitrates the single binding).

## Open questions

- **Punctuation / casing.** faster-whisper returns text with light punctuation
  in some models and none in others. v1: take the model's raw output verbatim;
  add a `transcript.post_process` config hook in v2.
- **Wake-word.** Not in v1.
- **Per-app behaviour.** Not in v1 (no special-casing for terminals, code
  editors, etc.).
