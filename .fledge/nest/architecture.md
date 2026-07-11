---
generated: 2026-07-11T05:16:32Z
commit: f5694b5bffd265badb03101b726304b5e6a0efb4
agent: fledge-forager
fledge_version: 0.4.0
---

# Architecture

Stenographer is a Wayland-only, local-only push-to-talk / toggle dictation daemon (Python ≥ 3.14). This document traces how a spoken utterance flows through the system end to end and how the major layers depend on each other.

## Layering

`cli.py` (`main()`) is the process entry point: it parses args via `_parser.py`, probes `Capabilities` (`capabilities.py`), loads `Config` (`config.py`), and — for `run`/`dictate` — wires every component together in `_build_session()` before constructing a `Session`.

`session.py:Session` is the single orchestrator for one utterance's lifecycle: hotkey → record → transcribe → output. Every callback from the hotkey listener, the recorder, and the ASR worker funnels through `Session` methods guarded by a shared `threading.RLock` (`session.py:_lock`), so concurrent key events, recorder callbacks (which run on the PortAudio thread), and shutdown signals cannot race.

Below `Session` sit four component layers, each independently testable and wired only through constructor injection (no module-level singletons):

- **`hotkey/`** — turns raw evdev key events into high-level actions. `binding.py:HotkeyBinding` parses/validates the configured key or chord; `state_machine.py:HotkeyStateMachine` is a **pure** (no I/O) state machine implementing the hybrid trigger (chord held ≥ threshold_seconds = PTT, short tap + second tap within double_tap_window_seconds = latched toggle); `listener.py:HotkeyListener` runs the evdev read loop (one reader thread per `/dev/input/event*` device, for multi-HID keyboards) and drives the state machine, invoking `Session` callbacks (`on_recording_start`, `on_recording_stop`, `on_toggle_off`, `discard_recording`, `cancel_all`).
- **`audio/`** — `capture.py:Recorder` captures mic audio via `sounddevice`/PortAudio, with a mono float32 ring buffer, sample-rate negotiation/resampling (`_resample_poly`, no scipy), and RMS-based silence detection; `feedback.py:Feedback` plays WAV cues (`assets/sounds/*.wav`) via `pw-play`/`paplay` subprocess, one of 11 named cues (`CueName`).
- **`asr/`** — `model.py:Model`/`LazyModel` wrap `faster_whisper.WhisperModel` for batch (`transcribe()`) and word-timestamped (`transcribe_words()`) decoding; `LazyModel` adds lazy load-on-first-use and idle-unload-after-timeout. `worker.py:Worker` runs transcription off the main thread via a job queue, supporting per-job cancellation (`threading.Event`) and unload routing (CTranslate2 `ReplicaPool` cleanup must happen on the worker thread). `streaming.py:StreamingTranscriber` is a **pure** LocalAgreement-N committer: a word is committed (and becomes typeable) only once the last N consecutive re-decodes agree on it, and the committed prefix is never revised.
- **`output/`** — `inject.py:Injector` types text at the cursor via `wtype` subprocess (stateless, degrades to a no-op + `False` return when `wtype` missing); `clipboard.py:ClipboardManager` writes (and, for tests, reads) the Wayland clipboard via `wl-copy`/`wl-paste` subprocess, populated independently of injection so it is the fallback when injection fails; `formatter.py:HeuristicFormatter` is a stateful, **append-only** formatter (spacing normalization, capitalization, pause-based paragraph breaks) — `feed()` for the live/incremental path (each committed token passes through exactly once), `format_batch()` for one-shot batch paths (paste mode, `transcribe FILE`).

`live.py:LiveStreamer` is the live-streaming driver that composes recorder partials → `worker.submit_words()` re-decode → `StreamingTranscriber` → `HeuristicFormatter.feed()` → `Injector.type_text(raw=True)`, active only in `injection_method == "text"` mode with `streaming.enabled`. Invariant: typed text is never revised, including on cancel — every intermediate typed state must be a prefix of the final transcript.

## Cross-cutting concerns

- **`config.py`** — frozen `Config` dataclass, nested per-concern sub-configs (`HotkeyConfig`, `AudioConfig`, `AsrConfig`, `FeedbackConfig`, `OutputConfig`, `ClipboardConfig`, `StreamingConfig`, `FormattingConfig`, `UpdateConfig`). `Config.defaults()` is the single source of truth for defaults; `Config.load(path)` parses TOML, validates per-section, merges with defaults.
- **`capabilities.py`** — `Capabilities.probe(cfg)` returns a frozen dataclass of 7 booleans (has_wtype, has_wl_copy, has_pw_play, has_paplay, has_input_group, has_mic, has_asr_model), checked before `run`/`dictate` launch; `doctor` subcommand surfaces these and exits 78 if a required one is missing.
- **`errors.py`** — `StenographerError` base and subclasses (`ConfigError`, `CapabilityError`, `AudioCaptureError`, `TranscriptionError`, `UpdateError`); policy functions `notify_failure()` (log ERROR, continue), `fatal()` (log CRITICAL, exit 78 default), `degrade_capability()` (log WARNING, continue). Components must raise these rather than inventing ad hoc error handling.
- **`notification.py`** — `DesktopNotification` wraps `notify-send` on a background worker thread (never blocks the caller); shows startup hint and listening/transcribing/model-loading/model-unloaded states; reuses notification IDs via `-p`/`-r`; no-ops and self-heals (with cooldown) if `notify-send` is unavailable.
- **`update.py`** — self-update from GitHub Releases: pure functions `check_for_update()`, `download_update()` (SHA-256 verified), `extract_to_staging()`, `apply_update()` (atomic two-step `os.rename` swap); `stop_daemon()`/`start_daemon()` wrap `systemctl --user`; `cli.py` wires these to an interactive prompt.
- **`bench.py`** — offline benchmarking harness (model × beam × compute_type matrix): cold-load time, RTF, WER (word-error-rate, with numeral normalization).

## Concurrency model

Three threads of control converge on `Session`: the hotkey listener's supervisor/reader threads, the recorder's PortAudio callback thread, and the ASR worker's job thread. `Session._lock` (RLock, reentrant so nested callback re-entry from `on_start`/`on_stop`/`on_toggle_off` doesn't deadlock) guards all mutable state transitions. One exception: `Session._enqueue_flush_segment()` (silence-detection flush callback, invoked directly on the PortAudio thread) touches only the thread-safe `queue.Queue` and reads plain attributes without taking the lock, by design (must be non-blocking). A generation counter (`Session._cancel_generation`) is bumped by `cancel_all()` so stale queue items (enqueued before cancellation) are dropped by the processor thread rather than processed — this pattern (generation tokens to invalidate stale async work) recurs in `LazyModel._load_generation` (idle-unload) and `HotkeyStateMachine._pending_generation` (double-tap timeout).

## Open Questions
- Exact interaction between `Session._recording_abort` (per-recording) and `LiveStreamer.abort` (per-streamer) — confirmed separate objects by inspection, but the full handoff sequence on cancel spans both `session.py` and `live.py`.
- Whether `Session.stop()`'s `join(timeout=60.0)` on the processor thread can leave work undrained if the thread hangs.
