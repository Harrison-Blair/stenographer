---
generated: 2026-07-11T05:16:32Z
commit: f5694b5bffd265badb03101b726304b5e6a0efb4
agent: fledge-forager
fledge_version: 0.4.0
---

# Domain

Glossary of business/domain concepts used throughout the codebase and its docs.

## Recording trigger modes
- **Push-to-talk (PTT)** — hold the configured hotkey/chord ≥ `hotkey.toggle_threshold_seconds` (default 0.5s); release stops recording and enqueues transcription.
- **Toggle** — short tap (< threshold) starts recording; a **double-tap** (second tap within `hotkey.double_tap_window_seconds`, default 0.35s) latches it into `TOGGLE_LATCHED`, which records until a third press/explicit stop. A short tap with no confirming second tap within the window auto-discards (`PENDING_TAP` → timeout → `discard_recording`).
- **Chord** — the configured hotkey, which may be a single evdev key (`KEY_RIGHTCTRL`) or a `+`-joined combination (`KEY_LEFTCTRL+KEY_A`), canonicalized by case-insensitive sort.
- **Cancel chord** — a separate configured binding (`hotkey.cancel_binding`) that aborts the in-progress recording/transcription entirely (already-typed text is not retracted).
- **Generation** — a monotonic counter bumped on cancel/reset that invalidates stale asynchronous callbacks (timers, queued items) tied to an earlier state; recurs independently in the hotkey state machine, the session's cancellation path, and the ASR lazy-model idle-unload path.

## Utterance lifecycle
- **Utterance** — one spoken input, from recording start to text output; queued and processed asynchronously by `Session`.
- **Segment** — a flushed chunk of audio (silence-triggered mid-recording flush, or the final stop) submitted to the transcriber.
- **Silence detection / flushing** — RMS-based classifier; a silence gap ≥ `audio.silence_duration_seconds` after prior detected speech (RMS ≥ `audio.silence_rms_threshold`) triggers an early segment flush, reducing latency for multi-clause utterances. Disabled during live streaming and in one-shot mode.
- **Batch (assembled transcription)** — the traditional path: record the full utterance → transcribe once → inject/paste once, with silent segments filtered by `no_speech_prob`.
- **Streaming (live typing)** — real-time path: recorder partials feed a word-timestamped re-decode loop; only *committed* words are typed, immediately, as audio continues. Mode is `"text"` injection only; **removed then rebuilt** (per project memory) with coalescing + a single final decode.
- **Injection method** — `"text"` (direct typing via `wtype`) or `"paste"` (clipboard write + simulated Ctrl+V, via `wtype -M ctrl v -m ctrl`).
- **Raw injection** — typed text bypassing the formatter's whitespace/case/length normalization (used for already-formatted live partials).

## ASR concepts
- **ASR (Automatic Speech Recognition)** — offline, English-only, via faster-whisper; model never bundled, fetched separately (~800 MB) with `stenographer model download`.
- **Compute type** — inference quantization mode (`int8`, `int8_float16`, `float16`, `float32`); trades speed for quality.
- **Beam size** — beam-search width for decoding; streaming may use a smaller interim beam and the configured (larger) beam only at finalization.
- **Lazy / eager ASR mode** — lazy: model loads on first hotkey press and unloads after `idle_unload_seconds` of inactivity (lower memory, slower first press); eager: model loaded at daemon start.
- **LocalAgreement-N** — the live-streaming commit policy (Macháček et al., `whisper_streaming`): a word becomes committed (typed, irreversible) only once the last N consecutive re-decodes agree on it.
- **Hypothesis** — the full word list from one re-decode over the current audio window.
- **Committed prefix / uncommitted tail** — words that have achieved N-way agreement (immutable) vs. words in the latest hypothesis beyond that point (still revisable).
- **Rebase** — trimming the audio window from its start and shifting the committer's internal offset so future commits still convert to absolute time correctly.
- **WER (Word Error Rate)** — Levenshtein distance between reference and hypothesis transcripts, normalized by reference length; used in `bench.py`.
- **RTF (Real-Time Factor)** — inference time ÷ audio duration; <1.0 is faster than real time.

## Output concepts
- **Formatter (HeuristicFormatter)** — append-only text formatter: spacing normalization, sentence capitalization, pause-based paragraph breaks (`paragraph_pause_seconds` gap between tokens inserts a blank line). Safe in the live typing path because it never revises already-emitted output.
- **Clipboard fallback** — the Wayland clipboard is always populated independently of injection, so it's the recovery path when `wtype` injection fails.

## Platform / environment concepts
- **Wayland-only** — requires a compositor implementing `zwp-input-method-protocol-unstable-v1` (wlroots, Hyprland, Sway, KWin, Mutter) for `wtype` to function.
- **Input group** — Unix group membership required to read `/dev/input/event*` for hotkey capture; probed as a required `Capabilities` flag.
- **Capability degradation** — optional capabilities (wtype, wl-copy, notify-send) missing → warn and continue; required capabilities (input group, mic, ASR model) missing → fatal, exit 78.
- **Desktop notification** — async, non-blocking `notify-send`-backed status surface (listening / transcribing / model-loading / model-unloaded / startup hint); no-ops when `notify-send` absent.

## Release/versioning concepts
- **VERSION** — `[project].version` in `pyproject.toml`; single source of truth; every merge to `main` must bump it before the release workflow will publish.
- **Frozen binary / onedir** — the PyInstaller-built, self-contained distributable (`dist/stenographer/stenographer`), requiring no system Python.
