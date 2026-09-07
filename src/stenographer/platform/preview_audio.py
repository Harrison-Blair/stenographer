# SPDX-License-Identifier: GPL-3.0-or-later
"""PortAudio output-only cue adapter for native desktop setup.

Imports audio libraries only at explicit playback; construction neither probes
nor opens a microphone. Native playback acceptance is a separate manual gate.
"""

from __future__ import annotations

import contextlib
import threading
import time
from pathlib import Path


class PortAudioCuePlayer:
    def __init__(self) -> None:
        self._lock = threading.Lock()

    def play(self, path: Path, volume: float) -> None:
        def play_once():
            # Runtime cues are best effort; never print paths or native
            # exception text from a background callback/thread.
            with contextlib.suppress(Exception):
                self.preview(path, volume)

        threading.Thread(target=play_once, daemon=True, name="cue-playback").start()

    def preview(
        self, path: Path, volume: float, *, cancellation: threading.Event | None = None
    ) -> None:
        import sounddevice
        import soundfile

        with self._lock:
            if cancellation is not None and cancellation.is_set():
                raise RuntimeError("Sound preview cancelled")
            samples, rate = soundfile.read(path, dtype="float32", always_2d=True)
            samples *= volume
            cursor = 0
            finished = threading.Event()

            def callback(output, frames, timing, status):
                nonlocal cursor
                count = min(frames, len(samples) - cursor)
                output[:count] = samples[cursor : cursor + count]
                output[count:] = 0
                cursor += count
                if cursor >= len(samples):
                    raise sounddevice.CallbackStop

            if cancellation is not None and cancellation.is_set():
                raise RuntimeError("Sound preview cancelled")
            with sounddevice.OutputStream(
                samplerate=rate,
                channels=samples.shape[1],
                dtype="float32",
                callback=callback,
                finished_callback=finished.set,
            ) as stream:
                deadline = time.monotonic() + 10
                while not finished.wait(0.02):
                    if cancellation is not None and cancellation.is_set():
                        stream.abort()
                        raise RuntimeError("Sound preview cancelled")
                    if time.monotonic() >= deadline:
                        stream.abort()
                        raise TimeoutError("Sound preview exceeded its playback deadline")
