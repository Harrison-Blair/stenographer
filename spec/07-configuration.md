<!--
SPDX-License-Identifier: GPL-3.0-or-later
-->

# 07 — Configuration

## Dependencies

- **Reads:** `00-overview.md` (glossary, components).
- **Blocks:** every component doc (`01`, `02`, `03`, `04`, `05`, `06`,
  `08`). They all consume keys defined here.

## Goal

Define the user-editable `config.toml` schema, its location, its defaults,
and the validation rules. Every other spec doc references keys from this
document by dotted path (e.g. `hotkey.binding`).

## File location and resolution order

1. `$STENOGRAPHER_CONFIG` (env var, absolute path) if set and readable.
2. `$XDG_CONFIG_HOME/stenographer/config.toml` (default
   `~/.config/stenographer/config.toml`).
3. If neither exists: write a default config to (2) on first daemon start,
   then load it.

The file is loaded once at startup. There is no `SIGHUP` reload in v1
(see `00-overview.md`).

## Schema (TOML)

The top-level table is `stenographer`. Every key below lives under it.

```toml
[stenographer]

# === Hotkey ===
# The keyboard binding that arms stenographer.
# Value: a string in evdev key-name syntax.
# See 01-hotkey.md for the grammar and accepted values.
hotkey.binding        = "KEY_RIGHTCTRL"   # default

# Press duration (seconds) below which a press counts as a tap,
# at or above which it is treated as push-to-talk.
hotkey.toggle_threshold_seconds = 0.5

# Window (seconds) after a short tap in which a second tap latches
# toggle recording. A lone tap is discarded when the window expires.
hotkey.double_tap_window_seconds = 0.35

# Cancel key: while the main chord is held, pressing this key discards
# the active recording, aborts in-flight transcription, and clears the
# queue. "" disables the cancel chord.
hotkey.cancel_binding = "KEY_ESC"

# Keyboard device path to grab. "" => auto-detect the first keyboard
# in /dev/input/event* owned by the user.
hotkey.device         = ""

# === Audio capture ===
# Sample rate fed into faster-whisper. faster-whisper resamples internally
# to 16 kHz; this is the device sample rate we request.
audio.sample_rate     = 16000

# Frame size passed to sounddevice.InputStream (frames per callback).
audio.frames_per_buffer = 1024

# Input device. "" => sounddevice default input.
# Run `stenographer devices` to list valid names / indices.
audio.input_device    = ""

# Hard cap on a single recording. When a capture reaches this many
# seconds the buffer is truncated (recording keeps running, but only
# the first max_recording_seconds are transcribed) and the error cue /
# notification fire. Guards against a forgotten toggle-on growing the
# buffer without bound. Set to 0 to disable the cap.
audio.max_recording_seconds = 600

# Mid-recording silence flush. While holding push-to-talk or with the
# toggle on, a pause of audio.silence_duration_seconds after real speech
# flushes the audio so far to transcription and keeps recording, so results
# appear sooner. false restores one-utterance-per-press behavior. Ignored by
# one-shot `dictate`.
audio.silence_detection = true

# RMS energy (0.0 .. 1.0 on float32 [-1, 1] audio) at or above which a block
# counts as speech; below it counts as silence.
audio.silence_rms_threshold = 0.01

# Seconds of continuous silence after speech before a flush fires.
audio.silence_duration_seconds = 1.5

# === ASR ===
# faster-whisper model identifier (HuggingFace repo id, or absolute local
# path). See 03-transcription.md.
asr.model             = "Systran/faster-whisper-large-v3"

# Language pinned for the model. The v1 spec mandates English.
asr.language          = "en"

# Beam size forwarded to faster_whisper.WhisperModel.transcribe.
asr.beam_size         = 5

# Compute type for CTranslate2. One of: "int8", "int8_float16",
# "float16", "float32", "default".
asr.compute_type      = "int8"

# Silence detection threshold. If all segments have no_speech_prob
# >= this value the utterance is treated as silence and skipped.
asr.silence_threshold = 0.6

# Model initialization mode. "eager" loads the model on daemon
# start (5-30 s boot). "lazy" loads on the first hotkey press
# (<1 s boot); the first press plays the model_loading cue and
# shows a loading notification, and transcription begins once the
# model is ready. One-shot commands always use eager.
asr.mode              = "lazy"

# Seconds of inactivity before the lazy-loaded model is unloaded
# from memory. Applies only when asr.mode = "lazy". Set to 0 to
# disable unloading (the model stays resident once loaded).
asr.idle_unload_seconds = 300

# === Audio feedback ===
# Volume for cue playback, 0.0 .. 1.0. Mapped to pw-play/paplay --volume.
feedback.volume       = 0.6

# Per-cue override. Keys are cue names from 04-audio-feedback.md
# (ptt_on, ptt_off, toggle_on, toggle_off, error, segment,
# transcribe_done, model_loading, model_ready). An unknown cue name
# is a config error. Values are absolute paths to a wav/ogg file.
# Missing key = use the bundled default cue of that name.
[stenographer.feedback.cues]
ptt_on          = null
ptt_off         = null
toggle_on       = null
toggle_off      = null
error           = null
segment         = null
transcribe_done = null
model_loading   = null
model_ready     = null

# Disable all audio feedback (true => never invoke pw-play/paplay).
feedback.mute = false

# === Text output ===
# How the transcript reaches the focused window. "paste" copies the
# text to the clipboard and simulates Ctrl+V (fast, robust for long
# text and non-Latin scripts, needs clipboard.enabled). "text" types
# the transcript with wtype, streaming each segment as it is decoded.
# See 05-text-output.md.
output.injection_method = "paste"

# Append a single space to the typed transcript (text mode only).
output.append_trailing_space = true

# Maximum number of characters to inject in a single wtype invocation.
# faster-whisper outputs are normally short; this is a sanity ceiling.
output.max_chars = 4096

# === Clipboard ===
# Copy the final transcript to the Wayland clipboard as well.
clipboard.enabled = true

# === Update ===
# GitHub OWNER/REPO queried by `stenographer update` for the latest
# release. See spec/12-update.md.
update.repo        = "Harrison-Blair/stenographer"

# Update channel. "stable" skips pre-release tags; "latest" includes
# them. The CLI flag --prerelease overrides this for one invocation.
update.channel     = "stable"

# Base URL for the GitHub-compatible API. Override for GitHub
# Enterprise or a mirror. The release-list and asset-download
# endpoints are derived from this base.
update.base_url    = "https://api.github.com"

# Asset filename pattern, with {version} substituted. The release
# job in CI produces assets matching this template.
update.asset_pattern = "stenographer-{version}-linux-x86_64.tar.gz"

# HTTP timeout (seconds) for the API and the download.
update.timeout_seconds = 60
```

## Defaults (canonical list)

| Key                                          | Type     | Default                                    |
|----------------------------------------------|----------|--------------------------------------------|
| `hotkey.binding`                             | string   | `"KEY_RIGHTCTRL"`                          |
| `hotkey.toggle_threshold_seconds`            | number   | `0.5`                                      |
| `hotkey.double_tap_window_seconds`           | number   | `0.35`                                     |
| `hotkey.cancel_binding`                      | string   | `"KEY_ESC"` (empty string = disabled)      |
| `hotkey.device`                              | string   | `""` (empty string = auto-detect)          |
| `audio.sample_rate`                          | int      | `16000`                                    |
| `audio.frames_per_buffer`                    | int      | `1024`                                     |
| `audio.input_device`                         | string   | `""` (empty string = sounddevice default)  |
| `audio.max_recording_seconds`                | int      | `600` (`0` = uncapped)                      |
| `audio.silence_detection`                    | bool     | `true`                                     |
| `audio.silence_rms_threshold`                | number   | `0.01`                                     |
| `audio.silence_duration_seconds`             | number   | `1.5`                                      |
| `asr.model`                                  | string   | `"Systran/faster-whisper-large-v3"`        |
| `asr.language`                               | string   | `"en"`                                     |
| `asr.beam_size`                              | int      | `5`                                        |
| `asr.compute_type`                           | string   | `"int8"`                                   |
| `asr.silence_threshold`                      | number   | `0.6`                                      |
| `asr.mode`                                   | string   | `"lazy"`                                   |
| `asr.idle_unload_seconds`                    | int      | `300`                                      |
| `feedback.volume`                            | number   | `0.6`                                      |
| `feedback.cues.<name>`                       | string   | `""` (per cue; empty = bundled default)    |
| `feedback.mute`                              | bool     | `false`                                    |
| `output.injection_method`                    | string   | `"paste"`                                  |
| `output.append_trailing_space`               | bool     | `true`                                     |
| `output.max_chars`                           | int      | `4096`                                    |
| `clipboard.enabled`                          | bool     | `true`                                    |
| `update.repo`                                | string   | `"Harrison-Blair/stenographer"`           |
| `update.channel`                             | string   | `"stable"`                                |
| `update.base_url`                            | string   | `"https://api.github.com"`                |
| `update.asset_pattern`                       | string   | `"stenographer-{version}-linux-x86_64.tar.gz"` |
| `update.timeout_seconds`                     | int      | `60`                                      |

## Validation rules

- `hotkey.binding` must parse via the grammar in `01-hotkey.md`.
- `hotkey.toggle_threshold_seconds` must satisfy `0 < x <= 5`.
- `hotkey.double_tap_window_seconds` must satisfy `0 < x <= 2`.
- `hotkey.cancel_binding` must be empty (disabled) or parse via the
  grammar in `01-hotkey.md`, and must not share any key with
  `hotkey.binding`.
- `audio.sample_rate` must be one of `8000`, `16000`, `22050`, `44100`,
  `48000`.
- `audio.frames_per_buffer` must satisfy `64 <= x <= 8192`.
- `audio.max_recording_seconds` must satisfy `0 <= x <= 86400` (`0` = uncapped).
- `audio.silence_rms_threshold` must satisfy `0.0 <= x <= 1.0`.
- `audio.silence_duration_seconds` must satisfy `0 < x <= 10`.
- `asr.beam_size` must satisfy `1 <= x <= 10`.
- `asr.compute_type` must be one of the five allowed strings.
- `asr.silence_threshold` must satisfy `0.0 <= x <= 1.0`.
- `asr.mode` must be one of `"eager"`, `"lazy"`.
- `asr.idle_unload_seconds` must satisfy `0 <= x <= 86400`.
- `feedback.volume` must satisfy `0.0 <= x <= 1.0`.
- Every key under `feedback.cues` must be a known cue name (one of the
  nine in `04-audio-feedback.md`); an unknown name is a config error.
- `output.injection_method` must be one of `"paste"`, `"text"`.
- `output.max_chars` must satisfy `1 <= x <= 100000`.
- `update.channel` must be one of `"stable"`, `"latest"`.
- `update.asset_pattern` must contain the literal `{version}`.
- `update.timeout_seconds` must satisfy `1 <= x <= 600`.
- Any `feedback.cues.<name>` value, if non-empty, must point to a readable
  file. Empty string means "use the bundled default".
- The `hotkey.device` and `audio.input_device` values, if non-empty,
  must point to an existing path / valid device index. Empty string means
  "auto-detect" / "system default".

**TOML `null` is not supported.** `tomllib` rejects `null` literals
(TOML 1.0 has no null). Optional string fields use the empty string
`""` as the "unset" sentinel. The loader treats `""` as `None`
internally where appropriate.

On validation failure the daemon logs a precise error (file path + key +
expected type / range) and exits with code 78 (`EX_CONFIG`).

## Loading API

```python
# stenographer.config

@dataclass(frozen=True)
class Config:
    hotkey: HotkeyConfig
    audio: AudioConfig
    asr: AsrConfig
    feedback: FeedbackConfig
    output: OutputConfig
    clipboard: ClipboardConfig
    update: UpdateConfig

    @classmethod
    def load(cls, path: pathlib.Path) -> "Config": ...

    @classmethod
    def defaults(cls) -> "Config": ...

    def write_default(cls, path: pathlib.Path) -> None: ...
```

The loader MUST:
1. Read the file with `tomllib.load` (stdlib, Python 3.11+; this project
   pins 3.14).
2. Merge the loaded table on top of `defaults()` so that any missing key
   takes the default.
3. Validate every key against the rules above.
4. Return a frozen `Config`. Components MUST treat `Config` as immutable.

## Out of scope (v1)

- Live reload (`SIGHUP`).
- Profile switching (`[profiles.<name>]`).
- Environment-variable interpolation beyond `STENOGRAPHER_CONFIG`.
- Schema migration if the on-disk file is older than the running version.

## Open questions

- Should we accept `XKB key names` (e.g. `Right Ctrl`) in addition to
  evdev names (`KEY_RIGHTCTRL`)? v1 spec restricts to evdev names to keep
  the grammar small; the `01-hotkey.md` spec will define the exact
  string format.
