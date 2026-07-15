---
generated: 2026-07-15T17:38:33Z
commit: d621b46261d9509fccbdffc4686be0b876c7951e
agent: fledge-forager
fledge_version: 0.5.4
---

# Data Model

The dataclasses, protocols, and state-carrying types that flow through the recording→transcription→output pipeline, plus config and packaging-adjacent schemas.

## Configuration (`src/stenographer/config.py`)

`Config` is the top-level dataclass loaded once from TOML at startup, with nine nested sub-configs (`src-core.md`):
- `HotkeyConfig` — `binding`, `toggle_threshold_seconds`, `double_tap_window_seconds`, `cancel_binding`, `device`, `prompt_binding`.
- `AudioConfig` — `sample_rate`, `frames_per_buffer`, `input_device`, `max_recording_seconds`, `silence_detection`, `silence_rms_threshold`, `silence_duration_seconds`.
- `AsrConfig` — `model`, `language`, `beam_size`, `compute_type`, `silence_threshold`, `mode` (`"eager"`/`"lazy"`), `idle_unload_seconds`.
- `FeedbackConfig` — `volume`, `cues` (dict keyed by `CueName`), `mute`.
- `OutputConfig` — `injection_method`, `append_trailing_space`, `max_chars`.
- `ClipboardConfig` — `enabled`.
- `StreamingConfig` — `enabled`, `min_chunk_seconds`, `agreement_n`, `beam_size`, `max_buffer_seconds`.
- `FormattingConfig` — `paragraph_pause_seconds`, `capitalize_sentences`, `normalize_spacing`.
- `UpdateConfig` — `repo`, `channel`, `base_url`, `asset_pattern`, `timeout_seconds`.
- `LlmConfig` — `base_url`, `model`, `system_prompt`, `timeout_seconds`, `temperature`, `max_tokens`.

Each section has a `_build_*` builder function with exhaustive range/enum validation; a bad value raises `ConfigError` with the dotted key path and reason (`src-core.md`).

## ASR types (`src/stenographer/asr/model.py`, `worker.py`, `streaming.py`)

- `SegmentInfo` (frozen) — `start: float`, `end: float`, `text: str`, `no_speech_prob: float`.
- `WordInfo` (frozen) — `start: float`, `end: float`, `word: str`, `probability: float`; the unit streaming operates on.
- `TranscriptionResult` (frozen) — `text: str`, `duration_seconds: float`, `segments: list[SegmentInfo]`.
- `Job` (worker.py) — `samples: np.ndarray`, `future: Future[...]`, `on_segment`, `cancel_event`, `kind: Literal["segments","words"]`, `beam_size`. Enqueued by `submit()`/`submit_words()`.
- `CancelledError` — raised on the worker thread when cancellation fires mid-transcription; propagated via `Future.set_exception()`.
- `_UNLOAD` sentinel (worker.py) — distinguishes a lazy-model-unload request from a real `Job` on the queue.

## Session / live-streaming state (`session.py`, `live.py`)

- `_BatchItem` — `samples`, `mode` (`"ptt"`/`"toggle"`), `abort`, `generation`, implicit source.
- `_LiveItem` — `streamer`, `generation`.
- Session tracks `_recording` flag, `_recording_source` (`"dictate"`/`"prompt"`), `_cancel_generation` counter, per-recording abort `Event`, all guarded by an `RLock`.
- `live.py` sentinels: `_PARTIAL`, `_FINAL`, `_ABORT` (module-level strings); `_HIDE` object for the notification queue.

## Capabilities & updates

- `Capabilities` (frozen, `capabilities.py`) — booleans: `has_wtype`, `has_wl_copy`, `has_pw_play`, `has_paplay`, `has_input_group`, `has_mic`, `has_asr_model`.
- `UpdateInfo` (frozen, `update.py`) — `current_version`, `latest_version`, `tag_name`, `asset_url`, `asset_size`, `sha256_url`, `release_notes`, `prerelease`.

## Hotkey types (`hotkey/state_machine.py`, `binding.py`)

- `State` (Literal) — `"IDLE" | "RECORDING_PTT" | "PENDING_TAP" | "TOGGLE_LATCHED" | "TOGGLE_STOPPING"`.
- `Action` (Literal) — `"start_recording" | "stop_recording_ptt" | "stop_recording_toggle" | "latch_toggle" | "await_double_tap" | "discard_recording" | "cancel" | "noop"`.
- `Transition` (NamedTuple) — `action: Action`, `cue: str | None` (e.g. `"ptt_on"`, `"toggle_off"`, `"discard"`, `"cancel"`, or `None`).
- `HotkeyBinding` — immutable, hashable; stores canonicalised `_keys: tuple[str, ...]`.
- Internal state-machine fields: `_state`, `_press_start`, `_chord_active`, `_consumed`, `_pending_generation` (invalidates stale double-tap timeouts).

## Audio/output types (`audio/capture.py`, `audio/feedback.py`, `output/*.py`)

- `CueName` (Literal union, `feedback.py`) — the 14 cue identifiers: `ptt_on`/`ptt_off`/`toggle_on`/`toggle_off` (+ `_prompt` variants), `cancel`, `discard`, `error`, `segment`, `transcribe_done`, `model_loading`, `model_ready`. Referenced by `FeedbackConfig.cues` in config, and must match `AudioConfig`/config schema.
- `_Token` (Protocol, `formatter.py`) — anything with `start: float`, `end: float`, and either a `word` or `text` field; satisfied by both `WordInfo` and `SegmentInfo`.
- `_FALLBACK_SAMPLE_RATES = (48000, 44100, 22050, 16000, 8000)`, `_FALLBACK_CHANNELS = (2, 1)`, `_MIN_SPEECH_SECONDS = 0.25` (capture.py fallback/gating constants).

## Benchmarking types (`bench.py`)

- `Clip` — `name`, `samples: np.ndarray`, `duration`.
- `BatchRow` — `model`, `beam`, `compute`, `load_s`, `rtf`, `wer`, `is_gold`, `text`.

## Packaging/release-adjacent schemas

- GitHub Actions workflow YAML schema (`on`, `jobs`, `runs-on`, `steps`, `permissions`, `concurrency`) (`.github.md`).
- Badge JSON (shields.io format): `{"schemaVersion": 1, "label": "release", "message": "<tag|unreleased>", "color": "<brightgreen|orange>"}` (`.github.md`).
- Version string: `X.Y.Z` extracted from `pyproject.toml` via `tomllib`, tagged `v${VERSION}` (`.github.md`).

## Open Questions

- What `compute_type` values does `AsrConfig` accept, and what are their CPU/GPU trade-offs? (`src-asr.md`)
- Are there size limits on audio samples passed to `transcribe`/`transcribe_words`, or does faster-whisper handle arbitrary lengths internally? (`src-asr.md`)
- Is `CueName` ever used to dispatch cue playback outside of `config.cues`, or is `Feedback.play()` always called by literal name string? (`src-core.md`)
