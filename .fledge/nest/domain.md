---
generated: 2026-07-15T17:38:33Z
commit: d621b46261d9509fccbdffc4686be0b876c7951e
agent: fledge-forager
fledge_version: 0.5.4
---

# Domain

Glossary of dictation-domain and project-specific terms used throughout the code and docs.

## Hotkey & recording modes

- **Hotkey binding** — an evdev key name (e.g. `KEY_RIGHTCTRL`) or `+`-separated chord (e.g. `KEY_LEFTCTRL+KEY_RIGHTCTRL`), user-configurable in `[stenographer.hotkey]` (`root.md`, `src-hotkey.md`).
- **PTT (push-to-talk)** — hold the chord ≥ `toggle_threshold_seconds` (default 0.5s), release to stop; emits `ptt_on`/`ptt_off` cues.
- **Toggle** — press the chord for less than the threshold, then a second tap within `double_tap_window_seconds` (default 0.35s) latches recording on; a third press stops it; emits `toggle_on`/`toggle_off` cues.
- **Chord** — one or more keys pressed simultaneously; order-invariant after `HotkeyBinding` canonicalization.
- **Double-tap** — the two quick presses that transition `PENDING_TAP` → `TOGGLE_LATCHED`.
- **Generation (counter)** — invalidates stale double-tap timeouts / cancel callbacks once a state transition has superseded them (`hotkey/state_machine.py`, `session.py`).
- **Device reacquisition** — if all evdev devices are lost, the listener re-scans `/dev/input/event*` with exponential backoff (retry interval 2s, timeout 30s).
- **Multi-HID keyboard** — one physical keyboard exposing multiple `/dev/input/event*` interfaces (e.g. QMK/VIA firmware); the listener multiplexes all of them and shares the held-key set so a keydown on one and release on another still resolves correctly.
- **Cancel** — ESC (or configured `cancel_binding`) discards all active recording, queued utterances, and in-flight transcription; already-typed text is left in place (no undo).
- **Discard** — throws away a short-tap recording on double-tap-window expiry; only the owning hotkey may discard it.
- **Prompt / prompt mode** — an optional secondary hotkey (`prompt_binding`) that captures a batch recording and routes it to a local LLM for rewriting before typing (`source="prompt"`).

## Transcription & streaming

- **ASR** — Automatic Speech Recognition; offline, English-only, via `faster-whisper`.
- **Utterance** — one press-release hotkey cycle (PTT/toggle) or one `dictate` invocation, routed through the session queue.
- **Batch / batch item** — a pre-stop or mid-recording silence-flushed audio segment queued whole for transcription.
- **Model mode** — `"eager"` loads the ASR model at daemon startup; `"lazy"` defers load to first recording and unloads after `idle_unload_seconds` of inactivity.
- **LazyModel / idle-unload** — deferred model loading; drops the loaded `WhisperModel` after a configurable idle period to free memory.
- **Segment** — one contiguous span of ASR output with text and a `no_speech_prob` confidence score.
- **beam_size** — faster-whisper decoding parameter trading quality for speed.
- **compute_type** — faster-whisper backend precision (int8/float16/float32/etc.), set in `AsrConfig`.
- **Live streaming** — optional mode (`[stenographer.streaming]`, `text` output mode only): partial transcription → coalesce → word-timestamped re-decode → commit → format → typed delta.
- **Re-decode** — the live driver re-processes a growing audio window on each recording chunk to produce updated word hypotheses.
- **LocalAgreement-N** — word-commitment policy: a word is committed (typed) only after N consecutive re-decodes agree on it; the committed prefix is never revised (reference: Macháček et al., "Turning Whisper into Real-Time Transcription System").
- **Committed / commitment** — words confirmed by LocalAgreement-N and passed to output; irreversible, since `wtype` cannot un-type.
- **Window-local timestamps** — times relative to the current trimmed audio window; converted to absolute time via an internal offset.
- **Tail-silence guard** — trims trailing silence from the live audio window while preserving quiet-mic speech (noise-floor relative, not an absolute RMS default — Harrison's own speech can fall below RMS 0.01).
- **Rebase** — updates the streaming committer's internal offset after the audio window is trimmed.
- **RTF (real-time factor)** — ratio of transcription wall-clock time to audio duration; used in `bench.py` and noted as still unmeasured on real CPU hardware for streaming mode.
- **WER (word error rate)** — benchmarking metric in `bench.py`, computed with number-word normalization.

## Audio capture & output

- **RMS threshold** — root-mean-square energy floor (0.01 default, user-configurable) below which audio is classified as silence.
- **Silence detection** — frame-by-frame RMS tracking; flushes a segment after `silence_duration_seconds` of continuous low energy, guarded by a minimum accumulated real-speech duration (`_MIN_SPEECH_SECONDS`) to avoid flushing on clicks/coughs.
- **Polyphase FIR resampling** — dependency-free (no scipy) rational-rate audio resampling used when the device falls back to a different sample rate than requested.
- **Cue** — a short synthetic audio feedback signal (`ptt_on`, `toggle_off`, `error`, etc., 44.1 kHz PCM_16 WAV) confirming a state transition or alerting to an error.
- **Injection / Injector** — typing text at the active cursor position in the focused Wayland window via the `wtype` subprocess.
- **Clipboard fallback** — since `wl-copy` writes the transcript independently of injection, the clipboard is always the fallback if `wtype` injection fails.
- **Append-only formatter** — `HeuristicFormatter` in the streaming path: every fed token only ever appends to output; the committed prefix is never revised (mirrors the LocalAgreement invariant).
- **Finalize** — end-of-utterance cleanup: emits a trailing space if configured, then resets formatter state.

## Packaging & release

- **Frozen binary** — the PyInstaller-bundled executable (`dist/stenographer/stenographer`), a self-contained "onedir" with Python runtime, modules, assets, and launcher stub.
- **PyInstaller hook / runtime hook** — a `hook-*.py` customizes what PyInstaller bundles/excludes at analysis time; a `rthooks/py_rth_*.py` runs at frozen-binary startup to prepare the environment (e.g. setting `LD_LIBRARY_PATH` so `sounddevice` finds system `libportaudio`).
- **onedir** — PyInstaller bundling mode producing a directory of the binary + dependencies, as opposed to a single-file "onefile" archive.
- **SHA-256 verification** — `install.sh` and `update.py` both verify downloaded release tarballs against a published checksum before installing.
- **Systemd user service** — a per-user (not system-wide) daemon unit (`WantedBy=graphical-session.target`), managed via `stenographer enable`/`start`/`stop`/`disable`.
- **Release** — a versioned GitHub Release tied to git tag `v${VERSION}`, published with a tarball, SHA-256 checksum, and `install.sh`; the release workflow refuses to republish an already-used version.
- **Badge** — a shields.io-format JSON status file on an orphan `badges` branch reflecting the latest release tag.

## Open Questions

- Are there plans for multi-language support, or is English-only a permanent design constraint? (`root.md`)
- Is the noise-floor / tail-silence estimation validated for non-speech audio, or tuned specifically for speech? (`src-core.md`)
- What Wayland compositors (wlroots, Hyprland, Sway, KWin, Mutter) are actually tested vs. merely mentioned in docs? (`root.md`)
