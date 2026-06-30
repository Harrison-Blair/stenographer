<!--
SPDX-License-Identifier: GPL-3.0-or-later
-->

# 02 — Audio capture

## Dependencies

- **Reads:** `00-overview.md` (Recorder definition, lifecycle).
- **Reads:** `07-configuration.md` (`audio.*` keys).
- **Reads:** `09-error-handling.md` (capability policy, runtime error policy).
- **Reads:** `10-packaging.md` (`sounddevice` dep, capability list).
- **Blocks:** `03-transcription.md` consumes the buffer this component
  produces.
- **Blocks:** `08-process-model.md` constructs the Recorder.

## Goal

Specify the `Recorder` component: how mic audio is captured, buffered,
and handed to the transcription worker, in a way that is safe to share
with the audio-feedback thread (which uses the same PipeWire / PulseAudio
session) and that survives mid-utterance device errors.

## Stream parameters

| Parameter        | Value                                                   | Source                                  |
|------------------|---------------------------------------------------------|-----------------------------------------|
| `samplerate`     | `cfg.audio.sample_rate` (default `16000`)               | `07-configuration.md`                   |
| `channels`       | `1` (mono)                                              | spec                                    |
| `dtype`          | `"float32"`                                             | spec                                    |
| `blocksize`      | `cfg.audio.frames_per_buffer` (default `1024`)          | `07-configuration.md`                   |
| `device`         | `cfg.audio.input_device` or `None` (sounddevice default) | `07-configuration.md`                 |
| `latency`        | `"high"`                                                | spec (we don't need real-time)          |
| `callback`       | `Recorder._on_audio`                                    | this doc                                |

faster-whisper resamples from this rate to 16 kHz internally. 16 kHz is
the default device rate to keep that no-op, but the spec allows
`8000`, `22050`, `44100`, or `48000` (validated in `07-configuration.md`).

## Buffer representation

A recording is a `numpy.ndarray` of shape `(n_samples, 1)` and dtype
`float32`, in `[-1.0, 1.0]`. Values outside that range are clamped by
PortAudio before the callback receives them.

The Recorder accumulates into a `bytearray` of raw `float32` samples
inside the PortAudio callback, then **outside** the callback
reinterprets it as `ndarray` when `stop()` is called. This avoids
holding the GIL inside the audio thread for longer than the copy.

## Threading

- The PortAudio callback runs on a sounddevice-managed thread.
  The callback MUST be non-blocking and MUST NOT call any
  Python code that could deadlock (no logging from inside the callback;
  push a "frame received" sentinel into a `queue.Queue` and let the
  Recorder main thread log at stop time).
- The Recorder main thread is a `threading.Thread` started by
  `Session.start_recording()`. Its job is to own the
  `sounddevice.InputStream` lifecycle and join on the audio thread at
  stop.
- The transcribed handoff is: `Recorder.stop() -> numpy.ndarray` ->
  `Worker.submit(buffer)` (see `03-transcription.md`).

## API

```python
# stenographer.audio.capture

from typing import Callable, Optional
import numpy as np

class Recorder:
    def __init__(
        self,
        *,
        sample_rate: int,
        frames_per_buffer: int,
        device: Optional[str | int],
        on_error: Callable[[Exception], None],
    ) -> None: ...

    def start(self) -> None:
        """Open the InputStream and begin accumulating samples."""

    def stop(self) -> np.ndarray:
        """Close the stream, return the accumulated mono float32 buffer."""

    @property
    def is_active(self) -> bool: ...

    @staticmethod
    def default_input_device_name() -> Optional[str]:
        """For the startup probe (see 10-packaging.md)."""
```

`start()` and `stop()` MUST be called from the same thread (the
`Session` main thread). The constructor does not open the device.

## Startup probe (capability check)

Called by `Capabilities.probe()` (see `10-packaging.md`):

```python
result = sounddevice.query_devices(kind="input")
# result is a single dict (the default input device) or an empty dict
has_mic = bool(result)
```

If this raises `sounddevice.PortAudioError`, or `result` is empty,
`has_mic` is `False` and the daemon exits 78 with the message:

```
stenographer: no usable input device.
  Detected devices:
    <sounddevice.query_devices() table>
  Set stenographer.audio.input_device in your config to a specific
  device, or fix your PipeWire / PulseAudio session.
```

## Mid-recording error handling

If the PortAudio callback reports an error (the callback receives a
`status` indicator of `paInputOverflow` or raises):

- The Recorder MUST call `on_error(exc)` exactly once.
- The Session MUST treat this as a discarded utterance: no transcription,
  no injection, no clipboard write. Fire the `error` cue via
  `errors.notify_failure` (see `09-error-handling.md`).
- The Recorder MUST be reusable: the next `start()` MUST open a fresh
  stream.

## Concurrent feedback playback

`audio/feedback.py` plays cues via `pw-play` or `paplay` (see
`04-audio-feedback.md`). These are **out-of-process** and use the same
PipeWire / PulseAudio session as the input stream, but on a different
device. The spec does NOT mandate exclusive capture mode; concurrent
playback is fine and is tested in the integration test.

## One-shot dictation mode

`stenographer dictate` and `stenographer transcribe FILE` share the
exact same `Recorder` class:

- `transcribe FILE`: skips the Recorder entirely. The file is read
  with `soundfile.read(..., dtype="float32", always_2d=True)` and the
  resulting `ndarray` is handed straight to the Worker.
- `dictate`: uses the Recorder exactly as the daemon does (start, wait
  for toggle-off, stop, hand off to Worker).

## Out of scope (v1)

- Multi-channel / stereo input.
- Per-utterance silence detection / VAD (faster-whisper handles
  silence natively).
- Microphone gain / AGC controls.
- Hot-pluggable input device switching mid-session.

## Open questions

- Should the Recorder expose a `level()` callback for a future "you are
  too quiet" cue? v1: no.
- Should the buffer be flushed to disk on `SIGTERM` so a crash
  preserves the last utterance? v1: no.
