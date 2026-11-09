# SPDX-License-Identifier: GPL-3.0-or-later
"""The speaker-separation helper process: one loaded library, many streams.

Commands arrive in order on one pipe; every ``push`` gets exactly one reply, so
the parent can bound the audio in flight. Replies carry segment times and
speaker numbers only, never audio.
"""

from __future__ import annotations

import multiprocessing
import os
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from stenographer.lib.platform.errors import NemoSpeechError
from stenographer.lib.platform.linux.nemo_speech import (
    Geometry,
    NemoSpeech,
    model_path,
    runtime_dir,
)
from stenographer.lib.platform.speaker_diarizer import finalize_all, split_final

if TYPE_CHECKING:
    import ctypes
    from multiprocessing.connection import Connection


@dataclass
class _Stream:
    handle: ctypes.c_void_p
    seconds_per_frame: float
    frames: int = 0
    final_until: float = float("-inf")


def _end_with_parent() -> None:
    # A parent that is killed runs no exit handlers, so the child ends itself.
    multiprocessing.parent_process().join()
    os._exit(1)


def child_main(commands: Connection, results: Connection, threads: int) -> None:
    # libgomp reads the limit once, when the library loads.
    os.environ["OMP_THREAD_LIMIT"] = str(threads)
    threading.Thread(target=_end_with_parent, daemon=True).start()
    try:
        api = NemoSpeech.load(runtime_dir())
    except OSError as exc:
        results.send(("failed", None, f"cannot load the speaker runtime: {exc}"))
        return
    results.send(("ready",))
    models: dict[Geometry, ctypes.c_void_p] = {}
    streams: dict[int, _Stream] = {}
    while True:
        try:
            message = commands.recv()
        except EOFError:
            return
        kind, sid = message[0], message[1]
        if kind != "open" and sid not in streams:
            continue  # the stream failed earlier; its failure was reported then
        try:
            if kind == "open":
                geometry = message[2]
                if geometry not in models:
                    models[geometry] = api.create(model_path(), geometry)
                model = models[geometry]
                streams[sid] = _Stream(api.open(model), api.seconds_per_frame(model))
                results.send(("opened", sid))
            elif kind == "push":
                stream = streams[sid]
                api.push(stream.handle, np.frombuffer(message[2], dtype=np.float32), message[3])
                frames = api.frame_count(stream.handle)
                if frames == stream.frames:
                    results.send(("pushed", sid))
                    continue
                stream.frames = frames
                new_final, tail, stream.final_until = split_final(
                    api.segments(stream.handle),
                    frames * stream.seconds_per_frame,
                    stream.final_until,
                )
                results.send(("update", sid, new_final, tail))
            elif kind == "finish":
                stream = streams[sid]
                api.finish(stream.handle)
                results.send(
                    ("finished", sid, finalize_all(api.segments(stream.handle), stream.final_until))
                )
            elif kind == "close":
                api.close(streams.pop(sid).handle)
        except NemoSpeechError as exc:
            stream = streams.pop(sid, None)
            if stream is not None:
                api.close(stream.handle)
            results.send(("failed", sid, str(exc)))
