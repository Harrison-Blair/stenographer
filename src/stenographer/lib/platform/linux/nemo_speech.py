# SPDX-License-Identifier: GPL-3.0-or-later
"""ctypes binding of the NeMo-Speech.cpp v0.3.0 speaker-diarization C API (``diar.h``).

Load it only in the helper process (``nemo_diarizer_child``): the library brings
its own libstdc++ and OpenMP, and reads ``OMP_THREAD_LIMIT`` when it loads.
"""

from __future__ import annotations

import ctypes
import platform
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path

import numpy as np

from stenographer.lib.platform.errors import NemoSpeechError
from stenographer.lib.platform.speaker_diarizer import SpeakerSegment

C_LIBRARY = "libnemo_speech_asr_c.so.1"
MODEL_FILENAME = "Nemotron-3-Diarization.q8_0.gguf"
CPUINFO = Path("/proc/cpuinfo")
NO_AVX2 = "speaker separation needs an AVX2 CPU"


@dataclass(frozen=True)
class Geometry:
    """A library preset plus overrides in 80 ms encoder frames (0 keeps the preset)."""

    preset: str
    chunk: int = 0
    right_context: int = 0
    left_context: int = -1
    fifo: int = 0
    spkcache: int = 0
    update_period: int = 0


OFFLINE = Geometry("v3-offline")
LIVE = Geometry("v3-streaming")


def runtime_dir(machine: str | None = None) -> Path:
    machine = machine or platform.machine()
    return Path(str(files("stenographer"))) / "assets" / "nemo_speech" / f"linux-{machine}"


def model_path() -> Path:
    return Path(str(files("stenographer"))) / "assets" / "models" / MODEL_FILENAME


def has_avx2(cpuinfo: str) -> bool:
    """True when every CPU's ``flags`` line lists ``avx2``. PURE."""
    flags = [
        line.split(":", 1)[1].split()
        for line in cpuinfo.splitlines()
        if line.startswith("flags") and ":" in line
    ]
    return bool(flags) and all("avx2" in cpu for cpu in flags)


def unavailable_reason(
    machine: str, cpuinfo: str, runtime_present: bool, model_present: bool
) -> str | None:
    """Why the runtime cannot run on this host, or ``None``. PURE."""
    if not runtime_present:
        return f"speaker separation is not available on {machine}"
    if machine == "x86_64" and not has_avx2(cpuinfo):
        return NO_AVX2
    if not model_present:
        return "the speaker model is missing from this installation"
    return None


def host_unavailable_reason() -> str | None:
    machine = platform.machine()
    cpuinfo = CPUINFO.read_text(encoding="ascii", errors="replace") if machine == "x86_64" else ""
    return unavailable_reason(
        machine,
        cpuinfo,
        (runtime_dir(machine) / C_LIBRARY).is_file(),
        model_path().is_file(),
    )


class _ModelConfig(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_size_t),
        ("model_path", ctypes.c_char_p),
        ("gpu", ctypes.c_int32),
        ("preset", ctypes.c_char_p),
        ("chunk_frames", ctypes.c_int32),
        ("right_context_frames", ctypes.c_int32),
        ("left_context_frames", ctypes.c_int32),
        ("fifo_frames", ctypes.c_int32),
        ("spkcache_frames", ctypes.c_int32),
        ("update_period_frames", ctypes.c_int32),
    ]


class _Segment(ctypes.Structure):
    _fields_ = [
        ("start_time", ctypes.c_double),
        ("end_time", ctypes.c_double),
        ("speaker", ctypes.c_int32),
    ]


@dataclass
class NemoSpeech:
    """The loaded C library."""

    lib: ctypes.CDLL = field(repr=False)

    @classmethod
    def load(cls, directory: Path) -> NemoSpeech:
        lib = ctypes.CDLL(str(directory / C_LIBRARY))
        p = ctypes.c_void_p
        lib.nemo_speech_asr_last_error.restype = ctypes.c_char_p
        lib.nemo_speech_diar_create.argtypes = [ctypes.POINTER(_ModelConfig), ctypes.POINTER(p)]
        lib.nemo_speech_diar_destroy.argtypes = [p]
        lib.nemo_speech_diar_destroy.restype = None
        lib.nemo_speech_diar_seconds_per_frame.argtypes = [p]
        lib.nemo_speech_diar_seconds_per_frame.restype = ctypes.c_double
        lib.nemo_speech_diar_stream_open.argtypes = [p, ctypes.POINTER(p)]
        lib.nemo_speech_diar_stream_push_f32.argtypes = [
            p,
            ctypes.POINTER(ctypes.c_float),
            ctypes.c_size_t,
            ctypes.c_int32,
        ]
        lib.nemo_speech_diar_stream_finish.argtypes = [p]
        lib.nemo_speech_diar_stream_close.argtypes = [p]
        lib.nemo_speech_diar_stream_close.restype = None
        lib.nemo_speech_diar_frame_count.argtypes = [p]
        lib.nemo_speech_diar_frame_count.restype = ctypes.c_int64
        lib.nemo_speech_diar_segments.argtypes = [
            p,
            p,
            ctypes.POINTER(_Segment),
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        return cls(lib)

    def _check(self, status: int, call: str) -> None:
        if status != 0:
            message = self.lib.nemo_speech_asr_last_error() or b""
            raise NemoSpeechError(f"{call}: status {status}: {message.decode('utf-8', 'replace')}")

    def create(self, model: Path, geometry: Geometry) -> ctypes.c_void_p:
        config = _ModelConfig(
            size=ctypes.sizeof(_ModelConfig),
            model_path=str(model).encode(),
            gpu=-1,  # a zeroed field would ask for GPU 0, which the CPU build rejects
            preset=geometry.preset.encode(),
            chunk_frames=geometry.chunk,
            right_context_frames=geometry.right_context,
            left_context_frames=geometry.left_context,
            fifo_frames=geometry.fifo,
            spkcache_frames=geometry.spkcache,
            update_period_frames=geometry.update_period,
        )
        handle = ctypes.c_void_p()
        self._check(
            self.lib.nemo_speech_diar_create(ctypes.byref(config), ctypes.byref(handle)), "create"
        )
        return handle

    def destroy(self, model: ctypes.c_void_p) -> None:
        self.lib.nemo_speech_diar_destroy(model)

    def seconds_per_frame(self, model: ctypes.c_void_p) -> float:
        return self.lib.nemo_speech_diar_seconds_per_frame(model)

    def open(self, model: ctypes.c_void_p) -> ctypes.c_void_p:
        stream = ctypes.c_void_p()
        self._check(
            self.lib.nemo_speech_diar_stream_open(model, ctypes.byref(stream)), "stream_open"
        )
        return stream

    def push(self, stream: ctypes.c_void_p, samples: np.ndarray, rate: int) -> None:
        samples = np.ascontiguousarray(samples, dtype=np.float32)
        pointer = samples.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        self._check(
            self.lib.nemo_speech_diar_stream_push_f32(stream, pointer, samples.size, rate), "push"
        )

    def finish(self, stream: ctypes.c_void_p) -> None:
        self._check(self.lib.nemo_speech_diar_stream_finish(stream), "finish")

    def close(self, stream: ctypes.c_void_p) -> None:
        self.lib.nemo_speech_diar_stream_close(stream)

    def frame_count(self, stream: ctypes.c_void_p) -> int:
        return self.lib.nemo_speech_diar_frame_count(stream)

    def segments(self, stream: ctypes.c_void_p) -> tuple[SpeakerSegment, ...]:
        """Segments under the library's default segmentation; speakers from 0."""
        count = ctypes.c_size_t()
        self._check(
            self.lib.nemo_speech_diar_segments(stream, None, None, 0, ctypes.byref(count)),
            "segments",
        )
        buffer = (_Segment * max(count.value, 1))()
        self._check(
            self.lib.nemo_speech_diar_segments(
                stream, None, buffer, count.value, ctypes.byref(count)
            ),
            "segments",
        )
        return tuple(
            SpeakerSegment(s.speaker - 1, s.start_time, s.end_time) for s in buffer[: count.value]
        )
