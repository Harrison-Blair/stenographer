---
generated: 2026-07-11T05:16:32Z
commit: f5694b5bffd265badb03101b726304b5e6a0efb4
agent: fledge-forager
fledge_version: 0.4.0
---

# Data Model

Core types and schemas defined in the codebase, with file references. No database — all state is in-process dataclasses and config-derived structures.

## Config (`config.py`)
`Config` — frozen dataclass, the entire user/system configuration, loaded once at startup from TOML. Nested sections:
- `HotkeyConfig`: `binding` (str, evdev key name or `+`-joined chord, e.g. `"KEY_RIGHTCTRL"`), `toggle_threshold_seconds` (float, default 0.5), `double_tap_window_seconds` (float, default 0.35), `cancel_binding` (str), `device` (str | None — auto-detect if empty).
- `AudioConfig`: `sample_rate` (int), `frames_per_buffer` (int), `input_device` (str | None), `max_recording_seconds` (int), `silence_detection` (bool), `silence_rms_threshold` (float, default 0.01), `silence_duration_seconds` (float, default 1.5).
- `AsrConfig`: `model` (str, default `"Systran/faster-distil-whisper-medium.en"`), `language` (str), `beam_size` (int), `compute_type` (str, default `"int8"`), `silence_threshold` (float — no-speech-prob cutoff), `mode` (str ∈ `["eager", "lazy"]`), `idle_unload_seconds` (int).
- `FeedbackConfig`: `volume` (float ∈ [0,1]), `cues` (dict[str, str | None] — per-cue WAV override), `mute` (bool).
- `OutputConfig`: `injection_method` (str ∈ `["text", "paste"]`), `append_trailing_space` (bool), `max_chars` (int, default 4096 — truncation limit in `Injector._prepare`).
- `ClipboardConfig`: `enabled` (bool).
- `StreamingConfig`: `enabled` (bool), `min_chunk_seconds` (float), `agreement_n` (int), `beam_size` (int | None — interim decode beam, may differ from finish beam), `max_buffer_seconds` (float).
- `FormattingConfig`: `paragraph_pause_seconds` (float), `capitalize_sentences` (bool), `normalize_spacing` (bool).
- `UpdateConfig`: `repo` (str, `"OWNER/REPO"`), `channel` (str ∈ `["stable", "latest"]`), `base_url` (str), `asset_pattern` (str, contains `{version}`), `timeout_seconds` (int).

## Capabilities (`capabilities.py`)
`Capabilities` — frozen dataclass, 7 booleans: `has_wtype`, `has_wl_copy`, `has_pw_play`, `has_paplay`, `has_input_group`, `has_mic`, `has_asr_model`. Produced by `Capabilities.probe(cfg)`.

## ASR types (`asr/model.py`)
- `SegmentInfo` (frozen): `start: float, end: float, text: str, no_speech_prob: float` — segment-level batch transcription metadata.
- `WordInfo` (frozen): `start: float, end: float, word: str, probability: float` — word-level timestamp/confidence, used by the streaming path.
- `TranscriptionResult` (frozen): `text: str, duration_seconds: float, segments: list[SegmentInfo] = []` — batch transcription result container.

## ASR worker types (`asr/worker.py`)
- `Job` (dataclass): `samples: np.ndarray, future: concurrent.futures.Future, on_segment: Callable | None, cancel_event: threading.Event | None, kind: Literal["segments","words"] = "segments", beam_size: int | None = None`.
- `CancelledError(Exception)` — raised when the Worker aborts an in-flight transcription.
- `_UNLOAD` sentinel — object marker on the job queue signaling an idle-unload request.

## Session types (`session.py`)
- `Session` — the orchestrator itself (not a data type but the central state container); relevant fields: `_recording: bool`, `_recording_abort: threading.Event`, `_active_abort: threading.Event | None`, `_cancel_generation: int`, `_utterance_queue: queue.Queue[tuple[np.ndarray, Literal["ptt","toggle"], threading.Event, int] | _LiveItem | None]`, `_live_streamer: LiveStreamer | None`.
- `_LiveItem` (dataclass): `streamer: LiveStreamer, generation: int` — queue payload for a streamed (as opposed to batch) utterance.

## Hotkey types (`hotkey/state_machine.py`, `hotkey/binding.py`)
- `State` (Literal): `"IDLE" | "RECORDING_PTT" | "PENDING_TAP" | "TOGGLE_LATCHED" | "TOGGLE_STOPPING"`.
- `Action` (Literal): `"start_recording" | "stop_recording_ptt" | "stop_recording_toggle" | "latch_toggle" | "await_double_tap" | "discard_recording" | "cancel" | "noop"`.
- `Transition` (NamedTuple): `action: Action, cue: str | None`.
- `HotkeyBinding` — immutable; `_keys: tuple[str, ...]` (case-insensitively sorted for chord canonicalization); methods `parse()`, `to_evdev_codes()`, `matches(set[int])`.

## Audio types (`audio/feedback.py`)
- `CueName` (Literal, 11 members): `"ptt_on" | "ptt_off" | "toggle_on" | "toggle_off" | "cancel" | "discard" | "error" | "segment" | "transcribe_done" | "model_loading" | "model_ready"`.

## Update types (`update.py`)
- `UpdateInfo` (frozen dataclass): `current_version: str, latest_version: str, tag_name: str, asset_url: str, asset_size: int, sha256_url: str, release_notes: str, prerelease: bool`.

## Benchmark types (`bench.py`)
- `BatchRow` (dataclass): `model: str, beam: int, compute: str, load_s: float, rtf: float, wer: float | None, is_gold: bool, text: str`.
- `Clip` (dataclass): `name: str, samples: np.ndarray (N,1) float32, duration: float`.

## Error types (`errors.py`)
- `StenographerError` (base, stores `message`) → `ConfigError` (adds `path`, `key`, `reason`), `CapabilityError`, `AudioCaptureError`, `TranscriptionError`, `UpdateError`.

## Output layer (no persistent types)
`output/inject.py:Injector`, `output/clipboard.py:ClipboardManager`, `output/formatter.py:HeuristicFormatter` are stateful/stateless wrapper classes, not data schemas — see `modules.md` / `architecture.md` for their contracts.
