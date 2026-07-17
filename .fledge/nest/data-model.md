---
generated: 2026-07-17T01:39:59Z
commit: 939420f205b102d61ab3d7ed257a1680a61483dc
agent: fledge-forager
fledge_version: 0.5.8
---

# Data Model

Core types, dataclasses, and schemas defined across stenographer, with the file each is defined in.

## Config schema (`src/stenographer/config.py`)

All frozen dataclasses, assembled into one `Config` root; loaded from TOML with `Config.load()` / `Config.defaults()`:

- `HotkeyConfig(binding, toggle_threshold_seconds, double_tap_window_seconds, cancel_binding, device, trigger_mode)` — `trigger_mode` added by commit f9d7ac2; validated against `ALLOWED_TRIGGER_MODES = frozenset({"hybrid", "toggle"})` (src-cli.md, src-hotkey.md).
- `AudioConfig(sample_rate, frames_per_buffer, input_device, max_recording_seconds, silence_detection, silence_rms_threshold, silence_duration_seconds)` — `silence_rms_threshold` default 0.01 (src-cli.md, src-audio.md).
- `AsrConfig(model, language, beam_size, compute_type, silence_threshold, mode, idle_unload_seconds)` — `compute_type` validated against `ALLOWED_COMPUTE_TYPES` (src-cli.md).
- `FeedbackConfig(volume, cues: dict[str, str|None], mute)`.
- `OutputConfig(injection_method, append_trailing_space, max_chars)` — `injection_method` validated against `ALLOWED_INJECTION_METHODS` (`"text"` | `"paste"`) (src-cli.md, src-output.md).
- `ClipboardConfig(enabled)`.
- `StreamingConfig(enabled, min_chunk_seconds, agreement_n, beam_size|None, max_buffer_seconds)`.
- `FormattingConfig(paragraph_pause_seconds, capitalize_sentences, normalize_spacing)`.
- `UpdateConfig(repo, channel, base_url, asset_pattern, timeout_seconds)` — `channel` validated against `ALLOWED_UPDATE_CHANNELS`.
- `ConfigError(path, key, reason)` — raised on validation failure with precise location info.

## Capabilities (`src/stenographer/capabilities.py`)

- `Capabilities` (frozen): `has_wtype, has_wl_copy, has_pw_play, has_paplay, has_input_group, has_mic, has_asr_model`. Produced by `Capabilities.probe()`.

## ASR types (`src/stenographer/asr/model.py`, `worker.py`, `streaming.py`)

- `SegmentInfo(start: float, end: float, text: str, no_speech_prob: float)` — frozen; one Whisper segment.
- `WordInfo(start: float, end: float, word: str, probability: float)` — frozen; one word from word-timestamped decode.
- `TranscriptionResult(text: str, duration_seconds: float, segments: list[SegmentInfo])` — frozen; batch transcription result.
- `Job(samples, future, on_segment, cancel_event, kind: Literal["segments","words"], beam_size)` — mutable; internal `Worker` queue item.
- `CancelledError` — raised in worker thread when a job's `cancel_event` or `Worker.cancel()` fires mid-transcription.
- `_UNLOAD` sentinel — placed on the worker queue by `LazyModel` to request model disposal on the worker thread.
- `StreamingTranscriber` internal state: `_history: deque[..., maxlen=agreement_n]`, `_offset` (window-local→absolute time conversion), committed-word list exposed via `committed_words`/`committed_text` properties.

## Session/live types (`src/stenographer/session.py`, `live.py`)

- `_BatchItem = tuple[np.ndarray, Literal["ptt","toggle"], threading.Event, int]` — (samples, mode, abort_event, generation).
- `_TaggedBatchItem` — `_BatchItem` + `Literal["dictate"]` source tag (legacy/optional).
- `_LiveItem` (dataclass): `streamer: LiveStreamer, generation: int`.
- `_ChunkItem` (dataclass): `samples: np.ndarray, abort: threading.Event, generation: int, offset_seconds: float, final: bool, mode: Literal["ptt","toggle"], source: Literal["dictate"]`.
- `Session` internal state (all guarded by `_lock: RLock`): `_recording: bool`, `_recording_source`, `_recording_abort: Event`, `_active_abort: Event|None`, `_cancel_generation: int`, `_utterance_queue: Queue`, `_processing_times: deque[float, maxlen=10]`, `_streaming: bool`, `_recording_streamer: LiveStreamer|None`, `_live_streamer: LiveStreamer|None`.
- `LiveStreamer` internal state: `_signals: Queue[tuple[str, ndarray|None]]` ("partial"/"final"/"abort"), `_trim_offset: float`, `_typed: str`, `_max_chars_hit: bool`.

## Hotkey types (`src/stenographer/hotkey/`)

- States (Literal, `state_machine.py`): `"IDLE" | "RECORDING_PTT" | "PENDING_TAP" | "TOGGLE_LATCHED" | "TOGGLE_STOPPING"`.
- Actions (Literal): `"start_recording" | "stop_recording_ptt" | "stop_recording_toggle" | "latch_toggle" | "await_double_tap" | "discard_recording" | "cancel" | "noop"`.
- `Transition(action: Action, cue: str|None)` — NamedTuple, returned by every `HotkeyStateMachine` event method.
- `HotkeyBinding(keys: tuple[str, ...])` — canonicalized (case-insensitive sorted) key-name tuple; `parse()`, `to_evdev_codes()`, `matches(event_keys: set[int])`.

## Audio types (`src/stenographer/audio/`)

- `Recorder._buffer: bytearray` (mono float32 bytes at device rate); audio arrays are `np.ndarray` shape `(N, 1)`, dtype `float32`, range `[-1, 1]`.
- `CueName` — `Literal` with 12 values: `"ptt_on", "ptt_off", "toggle_on", "toggle_off", "cancel", "discard", "error", "segment", "transcribe_done", "model_loading", "model_ready"` (feedback.py).

## Output types (`src/stenographer/output/`)

- `_Token` (Protocol, formatter.py) — duck-typed interface requiring `start: float`, `end: float`; satisfied by both `WordInfo` and `SegmentInfo`, letting the same formatter serve both the batch and live-typing paths.
- `Injector` state: `_available: bool`, `_append_trailing_space: bool` (default True), `_max_chars: int` (default 4096).
- `ClipboardManager` state: `_available: bool` only.
- `HeuristicFormatter` state: `_cfg: FormattingConfig`, `_started: bool`, `_prev_end: float`, `_capitalize_next: bool`.

## Update types (`src/stenographer/update.py`)

- `UpdateInfo(current_version, latest_version, tag_name, asset_url, asset_size, sha256_url, release_notes, prerelease)` — frozen.

## Bench types (`src/stenographer/bench.py`)

- `Clip(name: str, samples: np.ndarray, duration: float)`.
- `BatchRow(model, beam, compute, load_s, rtf, wer: float|None, is_gold: bool, text: str)`.

## Notification types (`src/stenographer/notification.py`)

- `DesktopNotification` state: `_queue: Queue[tuple[str,int]|object]`, `_worker: Thread|None`, `_last_id: int|None`, `_available: bool|None`; `_HIDE` sentinel object for the hide-state queue message.
