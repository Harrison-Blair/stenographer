---
generated: 2026-07-17T01:39:59Z
commit: 939420f205b102d61ab3d7ed257a1680a61483dc
agent: fledge-forager
fledge_version: 0.5.8
---

# Architecture

How stenographer's components are wired together, from hotkey press to typed/pasted output, and the invariants that hold the pipeline together.

## Overview

stenographer is a Wayland-only, local-only push-to-talk/toggle dictation daemon (`src/stenographer/`, root:CLAUDE.md). A global hotkey press → mic capture → offline ASR (faster-whisper) → text typed at the cursor (wtype) and copied to the Wayland clipboard (wl-copy). `Session` (session.py) is the single orchestrator: every callback from the hotkey listener, recorder, and ASR worker funnels through session methods guarded by an `RLock`, so concurrent key events and shutdown can't race (src-session-live.md).

## Pipeline

```
hotkey/listener.py (evdev read loop)
  → hotkey/state_machine.py (pure FSM: HotkeyStateMachine.on_keydown/on_keyup → Transition)
  → session.py Session.on_recording_start/on_recording_stop (callbacks, under Session._lock)
  → audio/capture.py Recorder (sounddevice/PortAudio capture, optional silence-detection flush)
  → asr/worker.py Worker (threaded, cancellable) → asr/model.py LazyModel/Model (faster-whisper)
  → output/formatter.py HeuristicFormatter (spacing/capitalisation/paragraph breaks)
  → output/inject.py Injector (wtype) and/or output/clipboard.py ClipboardManager (wl-copy)
```

`cli.py::_build_session()` wires all of the above into one `Session` (src-cli.md).

## Three processing pipelines inside Session (session.py)

Session routes each utterance into one of three pipelines, chosen by `cfg.audio.silence_detection`, `cfg.output.injection_method`, and `cfg.streaming.enabled` (src-session-live.md):

1. **Batch mode** (`_process`) — text injection without silence detection: `on_recording_stop` enqueues the whole recording; `Worker.submit()` transcribes, segments below `asr.silence_threshold` (no_speech_prob) are dropped, result is typed/pasted once.
2. **Paste-mode chunk aggregation** (`_process_chunk`) — `injection_method == "paste"` with silence detection: `Recorder`'s `on_segment` callback flushes mid-recording chunks, each decoded immediately via `Worker.submit()` and accumulated (`_chunk_segments`); the final chunk assembles the full utterance, formats it once, and performs a single clipboard-copy + paste.
3. **Streaming mode** (`_run_live`, via `live.py::LiveStreamer`) — `streaming.enabled` and `injection_method == "text"`: `Recorder`'s `on_partial` callback feeds `LiveStreamer.signal_partial()`; the streamer re-decodes the growing window (`Worker.submit_words()`), runs re-decodes through `asr/streaming.py::StreamingTranscriber` (a pure LocalAgreement-N committer), and types only newly-committed word deltas through `HeuristicFormatter.feed()` + `Injector.type_text()`.

All three pipelines are dispatched from a single consumer thread (`Session._process_utterance_queue`) reading a `queue.Queue`; a monotonic `_cancel_generation` counter lets `cancel_all()` drop stale in-flight items without blocking (src-session-live.md).

## Cross-module invariants

- **Typed text is never revised.** Every intermediate typed state (in streaming mode) must be a prefix of the final transcript — enforced jointly by `StreamingTranscriber` (asr/streaming.py, never revises committed words) and `HeuristicFormatter` (output/formatter.py, append-only `feed()`/`finalize()`). This invariant is the reason live.py, asr/streaming.py, and output/formatter.py must be reasoned about together (src-session-live.md, src-asr.md, src-output.md). Test coverage: `test_live.py::test_prefix_invariant_M6` reconstructs the formatted batch transcript from typed deltas.
- **Clipboard is an independent, always-populated fallback.** `ClipboardManager.copy()` is called regardless of injection success so paste is always possible if `Injector.type_text()` fails (src-output.md).
- **Capability degradation, not crashes.** `Injector`, `ClipboardManager`, and `DesktopNotification` all accept an `available: bool` at construction (from `capabilities.py::Capabilities.probe()`); when a required tool (wtype, wl-copy, evdev device, mic) is missing, calls are suppressed/logged rather than raising, except where `doctor`/`run` fail fast with exit 78 for genuinely required capabilities (src-cli.md, src-output.md).
- **State transitions are single-threaded per Session.** All state mutation (`_recording`, `_recording_streamer`, `_live_streamer`, `_cancel_generation`) happens under `Session._lock` (RLock); the PortAudio callback thread and hotkey listener thread only touch thread-safe queues or briefly-locked buffers (src-session-live.md, src-audio.md, src-hotkey.md).

## Planned changes (context for upcoming work)

Per the commissioning brief, three architectural surfaces are slated for near-term change:
- **Re-adding/extending text streaming** — touches `asr/streaming.py` (LocalAgreement-N committer) and `live.py` (LiveStreamer pipeline). Prior streaming work was rebuilt 2026-07-09 with coalescing + single final decode; real-CPU RTF remains unmeasured (src-session-live.md Open Questions).
- **Hotkey trigger mode → push-to-talk** — `hotkey/` currently supports only `ALLOWED_TRIGGER_MODES = {"hybrid", "toggle"}` (config.py, read via src-hotkey.md); there is no dedicated "ptt-only" mode yet. Commit f9d7ac2 added `hotkey.trigger_mode` config, consumed by `HotkeyStateMachine`'s constructor via `cli.py`.
- **wtype → paste-based injection** — `output/inject.py::Injector` already has a `paste()` method (Ctrl+V simulation via `wtype -M ctrl v -m ctrl`) alongside `type_text()`; `config.py::OutputConfig.injection_method` already supports `"text"` vs `"paste"` and Session already branches on it for chunk aggregation. The "replace wtype-based injector" work would extend/generalize this existing paste path (src-output.md, src-cli.md).

## Open Questions

- Exact live-streaming RTF (real-time factor) on real (non-benchmark) CPU hardware is unmeasured (src-session-live.md, src-asr.md).
- Whether a "ptt-only" (no toggle/double-tap) trigger mode is planned as a third `ALLOWED_TRIGGER_MODES` value, or whether "hybrid" is intended to remain the sole PTT-capable mode (src-hotkey.md).
