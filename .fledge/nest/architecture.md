---
generated: 2026-07-15T17:38:27Z
commit: d621b46261d9509fccbdffc4686be0b876c7951e
agent: fledge-forager
fledge_version: 0.5.4
---

# Architecture

How stenographer's pieces fit together end to end: the orchestrator, the pipeline it drives, and the cross-cutting policies every component follows.

## Overview

`stenographer` is a Wayland-only, local-only, offline dictation daemon: hotkey → record → transcribe → output (`src/stenographer/*`, per `root.md`). `cli.py:main` dispatches subcommands; the argument parser lives separately in `_parser.py` so the argcomplete hot path avoids heavy imports (`root.md`).

## The orchestrator: Session

`session.py:Session` is the single point of state transitions for one utterance. It funnels every callback — hotkey listener, recorder, ASR worker — through methods guarded by a re-entrant lock (`_lock`), so concurrent key events and shutdown signals can't race (`src-core.md`). It queues batch items (`_BatchItem`) and live items (`_LiveItem`) onto a processor thread, and exposes lifecycle callbacks for lazy ASR model loading (`src-core.md`).

Session owns cancel/discard semantics: **Cancel** (ESC / `cancel_binding`) discards all active recording, queued utterances, and in-flight transcription, but leaves already-typed text in place — there is no undo. **Discard** throws away a short-tap recording only if the hotkey that owns the active recording requests it (`src-core.md`). A `_cancel_generation` counter and per-recording abort `Event` prevent stale callbacks from acting on superseded state.

## Component pipeline

1. **`hotkey/`** (`src-hotkey.md`) — `listener.py:HotkeyListener` reads `/dev/input/event*` via `evdev`, multiplexing multiple HID interfaces for keyboards that expose several device paths, and dispatches through a **pure** state machine (`state_machine.py:HotkeyStateMachine`, no I/O/timers) implementing the hybrid trigger: short press (<0.5s) = toggle, long press (≥0.5s) = push-to-talk. `binding.py:HotkeyBinding` parses config strings like `"KEY_LEFTCTRL+KEY_RIGHTCTRL"` into canonical key-chord tuples.
2. **`audio/capture.py:Recorder`** (`src-audio.md`) — wraps PortAudio via `sounddevice`; RMS-based silence detection flushes segments; falls back across sample rates/channels on device errors, resampling with a dependency-free polyphase FIR filter.
3. **`asr/`** (`src-asr.md`) — `model.py:Model`/`LazyModel` wrap `faster-whisper`; `worker.py:Worker` runs transcription off the main thread with per-job cancellation (`submit` for batch, `submit_words` for word-timestamped re-decode); `streaming.py:StreamingTranscriber` is a **pure** LocalAgreement-N committer — a word is typed only after N consecutive re-decodes agree, and the committed prefix is never revised.
4. **`output/`** (`src-audio.md`) — `inject.py:Injector` types via `wtype` (falls back to clipboard paste on failure); `clipboard.py:ClipboardManager` writes via `wl-copy` independently, so it's always the fallback; `formatter.py:HeuristicFormatter` does append-only spacing/capitalisation/paragraph-break formatting, safe to call incrementally in the live typing path.
5. **`live.py:LiveStreamer`** (`src-core.md`) — the live streaming driver (`[streaming]` config, `text` mode only): recorder partials → coalesce → `submit_words` re-decode → committer → formatter → typed delta, with a tail-silence guard and window trimming at sentence boundaries or `max_buffer_seconds`. **Invariant: typed text is never revised** — every intermediate typed state is a prefix of the final transcript, including on cancel.

## Cross-cutting policies

- **`config.py`** — TOML schema (`Config` dataclass, 9 nested sub-configs), loaded once at startup; validated with exhaustive per-field range/enum checks; restart required to pick up edits (`src-core.md`).
- **`capabilities.py`** — `Capabilities.probe()` checks `wtype`, `wl-copy`, `pw-play`/`paplay`, `input` group membership, mic availability, and cached ASR model presence; backs the `doctor` subcommand.
- **`errors.py`** — all components raise `StenographerError` subclasses and route through `notify_failure` / `fatal` / `degrade_capability` rather than inventing ad hoc error handling; `doctor` and daemon startup exit 78 (`EX_CONFIG`) when a required capability is missing.
- **`notification.py`** — desktop notifications via `notify-send`, no-op if absent.
- **`update.py`** — self-update from GitHub Releases (SHA-256 verify, atomic two-rename install swap, daemon stop/start, exclusive flock update lock).
- **Single instance** — `cli.py` holds a `fcntl.flock` on `$XDG_RUNTIME_DIR/stenographer.lock` for the `run` subcommand.

## Packaging & distribution architecture

The frozen binary (PyInstaller, `packaging/stenographer.spec`) bundles the Python runtime and `stenographer` package (`collect_submodules`) but deliberately excludes system libraries (`libevdev`, `libportaudio`, `libGL`/Vulkan for onnxruntime) that must be present on the target machine — enforced by `hook-sounddevice.py` (excludes bundled audio libs) and `rthooks/py_rth_portaudio.py` (sets `LD_LIBRARY_PATH` at startup) (`packaging.md`). `scripts/install.sh` deploys the onedir bundle to `~/.local/share/stenographer/`, symlinks a launcher, and wires a systemd **user** service (`stenographer.service.in`, `WantedBy=graphical-session.target`) (`scripts.md`).

## Open Questions

- What is the exact lock-acquisition sequence for `Session.cancel_all()` vs. a concurrent `on_recording_stop()` arriving from two hotkey listeners on different threads? (`src-core.md`)
- How does `Session.attach_listener()` ordering prevent races during the window where `self._listener is None`? (`src-core.md`)
- Measured real-time factor (RTF) of live-streaming re-decodes on typical CPU hardware is still unmeasured (`root.md`, `src-core.md`).
- Why is `stenographer.llm` imported via `importlib.import_module()` in `session.py` (~line 691) rather than a top-level import? (`src-core.md`)
