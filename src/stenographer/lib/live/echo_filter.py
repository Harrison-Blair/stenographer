# SPDX-License-Identifier: GPL-3.0-or-later
"""Remove the system audio that the microphone hears from the microphone audio.

System audio plays on the speakers and comes back into the microphone as an echo.
The canceller subtracts it. It needs each microphone sample together with the system
sample of the same session position. The saved files of a session have this pairing,
and there the echo comes after its system audio.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

import numpy as np
import soundfile as sf

from stenographer.lib.audio.constants import SAMPLE_RATE

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    Cancel = Callable[[np.ndarray, np.ndarray], np.ndarray]

# A microphone block waits this long for the system samples of its position, then
# goes on without cleaning. The system samples of a position arrive after the
# microphone samples: by 0.05 to 0.26 s in recordings of up to three hours. The
# canceller finds an echo that is at most about 0.44 s after its system audio.
HOLD_SECONDS = 0.5
# System samples that no microphone block used are dropped after this time.
_KEEP_SECONDS = 2.0
# The canceller works on frames of 10 ms: a call with a part of a frame damages its output.
_FRAME = SAMPLE_RATE // 100
_FILE_CHUNK = 1000 * _FRAME


def make_canceller() -> Cancel:
    """Return ``cancel(microphone, system)`` of a new WebRTC echo canceller.

    Each call needs a whole number of 10 ms frames. The result has the length of the
    microphone samples and comes 8 ms late.
    """
    import pywebrtc_audio

    return pywebrtc_audio.EchoCanceller(sample_rate=SAMPLE_RATE, num_channels=1).process


class EchoFilter:
    """Pair live microphone blocks with system samples by session position and clean them.

    Positions are sample counts from the session start. The filter cleans only while
    the system source runs. Every microphone sample comes out once, in order. Not
    thread-safe: the caller holds one lock for all calls.
    """

    def __init__(self, cancel: Cancel | None = None, *, hold_seconds: float = HOLD_SECONDS) -> None:
        self._cancel = cancel if cancel is not None else make_canceller()
        self._hold = round(hold_seconds * SAMPLE_RATE)
        self._keep = round(_KEEP_SECONDS * SAMPLE_RATE)
        self._system_runs = False
        self._system = np.empty(0, dtype=np.float32)
        self._system_position = 0
        self._mic_position = 0
        # Microphone blocks that wait for system samples, each with its position.
        self._held: deque[tuple[int, np.ndarray]] = deque()
        self._held_samples = 0
        # Paired microphone and system samples that do not fill a canceller frame yet.
        self._pair = (np.empty(0, dtype=np.float32), np.empty(0, dtype=np.float32))
        self.cleaned_samples = 0
        # Samples that went on without cleaning while the system source ran.
        self.raw_samples = 0

    def start(self, source: str, position: int) -> None:
        """A run of *source* starts at session sample *position*."""
        if source == "mic":
            self._mic_position = position
        else:
            self._system_runs = True
            self._system = np.empty(0, dtype=np.float32)
            self._system_position = position

    def stop(self, source: str) -> list[np.ndarray]:
        """A run of *source* ends. Return the microphone audio that waits, not cleaned."""
        if source == "system":
            self._system_runs = False
            self._system = np.empty(0, dtype=np.float32)
        released = self._release_pair()
        while self._held:
            released.extend(self._release_raw())
        return released

    def system(self, samples: np.ndarray) -> list[np.ndarray]:
        """Add system samples. Return the microphone audio that is now ready, in order."""
        self._system = np.concatenate((self._system, samples))
        extra = self._system.size - self._keep
        if extra > 0:
            self._system = self._system[extra:]
            self._system_position += extra
        return self._ready()

    def mic(self, samples: np.ndarray) -> list[np.ndarray]:
        """Add one microphone block. Return the microphone audio that is now ready, in order."""
        position = self._mic_position
        self._mic_position += samples.size
        if not self._system_runs:
            return [samples]
        self._held.append((position, samples))
        self._held_samples += samples.size
        return self._ready()

    def _ready(self) -> list[np.ndarray]:
        ready = []
        while self._held:
            position, samples = self._held[0]
            first = position - self._system_position
            last = first + samples.size
            if first < 0:
                # The system run started after this block, or its samples were dropped.
                ready.extend(self._release_raw())
            elif last <= self._system.size:
                self._held.popleft()
                self._held_samples -= samples.size
                ready.extend(self._clean(samples, self._system[first:last]))
                self._system = self._system[last:]
                self._system_position += last
            elif self._held_samples > self._hold:
                ready.extend(self._release_raw())
            else:
                break
        return ready

    def _clean(self, mic: np.ndarray, system: np.ndarray) -> list[np.ndarray]:
        """Clean the whole frames of the paired samples; keep the rest for the next call."""
        mic = np.concatenate((self._pair[0], mic))
        system = np.concatenate((self._pair[1], system))
        whole = mic.size - mic.size % _FRAME
        self._pair = (mic[whole:], system[whole:])
        if not whole:
            return []
        self.cleaned_samples += whole
        return [self._cancel(mic[:whole], system[:whole])]

    def _release_raw(self) -> list[np.ndarray]:
        """Return the paired part of a frame and the oldest held block, not cleaned."""
        released = self._release_pair()
        _position, samples = self._held.popleft()
        self._held_samples -= samples.size
        self.raw_samples += samples.size
        return [*released, samples]

    def _release_pair(self) -> list[np.ndarray]:
        mic = self._pair[0]
        if not mic.size:
            return []
        self._pair = (np.empty(0, dtype=np.float32), np.empty(0, dtype=np.float32))
        self.raw_samples += mic.size
        return [mic]


def clean_file(mic: Path, system: Path, out: Path, cancel: Cancel | None = None) -> None:
    """Write the saved microphone audio *mic* to *out* with the echo of *system* removed.

    Microphone audio after the end of *system* is copied as it is.
    """
    cancel = cancel if cancel is not None else make_canceller()
    with sf.SoundFile(mic) as near, sf.SoundFile(system) as far:
        for audio in (near, far):
            if audio.samplerate != SAMPLE_RATE or audio.channels != 1:
                raise ValueError(f"session audio must be mono at {SAMPLE_RATE} Hz: {audio.name}")
        with sf.SoundFile(out, "w", SAMPLE_RATE, 1, format="FLAC", subtype=near.subtype) as cleaned:
            while True:
                samples = near.read(_FILE_CHUNK, dtype="float32")
                if not samples.size:
                    break
                reference = far.read(samples.size, dtype="float32")
                whole = reference.size - reference.size % _FRAME
                if whole:
                    cleaned.write(cancel(samples[:whole], reference[:whole]))
                cleaned.write(samples[whole:])
