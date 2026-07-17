---
generated: 2026-07-17T01:39:59Z
commit: 939420f205b102d61ab3d7ed257a1680a61483dc
agent: fledge-forager
fledge_version: 0.5.8
---

# Domain

Glossary of dictation/hotkey/streaming domain vocabulary used throughout stenographer's code, tests, and docs.

## Hotkey & trigger modes

- **Chord** — the set of evdev key codes currently held down (unioned across all attached HID devices for multi-function keyboards); exact-match against the configured binding.
- **Hotkey binding** — the configured evdev key name or chord (default `KEY_RIGHTCTRL`/`KEY_RIGHTALT` depending on doc), parsed by `hotkey/binding.py`.
- **Cancel binding** — separate hotkey (e.g. `KEY_ESC`) that aborts recording mid-stream; never lets already-typed text be un-typed.
- **Push-to-Talk (PTT)** — press-and-hold ≥ `toggle_threshold_seconds` (default 0.5s); recording active only while held; release stops.
- **Toggle** — short press (< threshold) latches recording on; a second short press latches it off.
- **Hybrid trigger mode** (`trigger_mode = "hybrid"`, default) — combines both: a short tap starts a double-tap window (second tap within it latches toggle); a long hold (≥ threshold) is PTT.
- **Toggle-only mode** (`trigger_mode = "toggle"`) — every press latches; hold duration never matters; double-tap window unused. `ALLOWED_TRIGGER_MODES = {"hybrid", "toggle"}` — no third "ptt-only" value exists yet (relevant to the planned trigger-mode work).
- **Double-tap window** — grace period (default 0.35s) after a short tap release during which a second tap latches toggle mode; expiry discards the pending tap.
- **Pending tap** — state between a short-tap release and either a second keydown (→ toggle latch) or timeout (→ discard).
- **Generation (hotkey)** — counter incremented on state transitions that invalidate a pending timer; the timer checks generation on fire to detect staleness (race-safe cancellation).
- **Main keyboard (auto-detection)** — a `/dev/input/event*` device with ≥10 letter keys and no "mouse"/"touchpad"/"consumer control" tokens in its name; used to auto-select the hotkey source device.

## Recording & audio

- **Silence detection** — RMS-based energy thresholding (`silence_rms_threshold`, default 0.01; `silence_duration_seconds`, default 1.5) used to flush mid-recording segments at pauses.
- **Flush** — emitting a buffered audio segment at a detected pause, guarded by a minimum-speech-duration floor (`_MIN_SPEECH_SECONDS = 0.25`) so short clicks/coughs don't trigger empty flushes.
- **Resampling (fallback)** — polyphase-FIR downsampling applied when the audio device only opens at a rate different from the configured one (cascades 48k→44.1k→22.05k→16k→8k).
- **Recorder snapshot** — a windowed view of currently-buffered audio from a given start offset, used by live streaming to grab the current partial window for re-decode.
- **Feedback cue** — a short WAV audio cue (`ptt_on`, `ptt_off`, `toggle_on`, `toggle_off`, `cancel`, `discard`, `error`, `segment`, `transcribe_done`, `model_loading`, `model_ready`) played via `pw-play`/`paplay` on state transitions.

## ASR & streaming

- **ASR model** — the faster-whisper checkpoint (default `Systran/faster-distil-whisper-medium.en`, ~800 MB); not bundled, fetched via `stenographer model download`; loaded lazily and unloaded after idle.
- **Lazy loading** — deferring ASR model load until first `transcribe()` call (`LazyModel`); model is dropped (with `gc.collect()`) after `idle_unload_seconds` of inactivity.
- **Generation token (ASR)** — `LazyModel._load_generation`, incremented on each transcribe; stale idle-unload requests (predating the latest transcribe) are dropped by comparing tokens.
- **Real-time factor (RTF)** — ratio of inference time to audio duration; RTF=1.0 means transcription takes exactly as long as the speech itself. Unmeasured on real (non-benchmark) hardware as of this scan.
- **Word error rate (WER)** — normalized Levenshtein edit distance over word tokens (`edits / max(ref_words, 1)`); used by `bench.py` against a gold reference config.
- **Streaming** (live output) — `live.py::LiveStreamer` pipeline: recorder partials → coalesce → `submit_words()` re-decode → LocalAgreement-N committer → formatter → typed delta.
- **Re-decode** — a fresh, full-window transcription hypothesis produced during live streaming; each re-decode is compared against prior ones for word agreement.
- **LocalAgreement-N** — the streaming commit policy (`asr/streaming.py::StreamingTranscriber`): a word is committed (and thus typed) only once it appears identically in the last N consecutive re-decodes. Reference: Macháček et al., "Turning Whisper into Real-Time Transcription System."
- **Committed word / committed prefix (invariant)** — once a word is committed by the LocalAgreement-N committer, it is never revised — the typed text is always a prefix of the eventual final transcript. Enforced jointly by `StreamingTranscriber` and the append-only `HeuristicFormatter`.
- **Window-local vs. absolute timestamps** — re-decode hypotheses carry timestamps relative to the current (possibly trimmed) decode window; converted to absolute utterance time via a running `_offset`.
- **Trim / rebase** — removing audio from the start of the decode window at a safe boundary (sentence terminal or `max_buffer_seconds`) to bound re-decode cost; `rebase()` adjusts the committer's time offset so subsequent commits keep correct absolute timestamps.
- **Tail-silence guard** — trims trailing sub-noise-floor audio before each interim re-decode, auto-scaled to the mic's ambient noise floor, to prevent Whisper from hallucinating text over silence.
- **no_speech_prob** — Whisper's per-segment confidence that a segment is silence/hallucination; segments at or above `asr.silence_threshold` are dropped rather than typed/pasted.
- **Chunk aggregation** — the paste-mode pipeline where silence-triggered chunks are decoded immediately but accumulated, with the final chunk triggering one assembled paste (as opposed to text mode's per-word streaming typing).

## Output & formatting

- **Injection** — typing text at the OS cursor via `wtype` (`Injector.type_text()`); the primary output path in `"text"` injection mode.
- **Paste mode** — output via clipboard population (`ClipboardManager.copy()`) followed by a simulated Ctrl+V (`Injector.paste()`); the alternate `injection_method` value, and the existing basis for the planned wtype→paste injection change.
- **Clipboard** — the Wayland clipboard (via `wl-copy`/`wl-paste`), populated independently of injection outcome so it always serves as a manual-paste fallback.
- **Formatting / append-only** — `HeuristicFormatter`'s spacing, capitalisation, and pause-based-paragraph-break logic; "append-only" means once text is emitted via `feed()`, it is never revised — required for the live-typing invariant to hold.
- **Paragraph pause** — a silence gap between tokens ≥ `formatting.paragraph_pause_seconds` that triggers a `\n\n` break and capitalises the next word.
- **Capability degradation** — the pattern (`available: bool` flag on `Injector`/`ClipboardManager`/`Feedback`/`DesktopNotification`) of suppressing and logging rather than raising when a required external tool is missing, so the daemon can still start in a degraded mode.

## Daemon / operational

- **Doctor** — the `stenographer doctor` capability probe; validates wtype, wl-copy, audio player, input group, mic, ASR model presence; exits 78 if a required capability is missing.
- **Input group** — the Linux group required to read `/dev/input/event*` for hotkey detection; users must be a member.
- **Single-instance lock** — `fcntl.flock` on `$XDG_RUNTIME_DIR/stenographer.lock`, preventing concurrent daemon instances; the lock file also stores the daemon PID for manual recovery.
- **Onedir bundle** — the PyInstaller `--onedir` self-contained binary tree; self-update swaps the entire directory atomically (two-step rename: target→backup, source→target).

## Open Questions

- Whether a dedicated "ptt-only" (no toggle) trigger mode is a planned third `ALLOWED_TRIGGER_MODES` value, distinct from today's "hybrid" (src-hotkey.md).
- Whether the default `silence_rms_threshold` of 0.01 needs revisiting for quiet mic input, per existing project memory that Harrison's speech can fall below RMS 0.01 (src-audio.md; corroborated by project MEMORY.md's "Quiet mic RMS" note).
