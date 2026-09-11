# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared injected collaborators for the real daemon policy.

No stand-in mocks native calls: lifecycle, processing, measurements, and summary
rendering all execute the shipping implementation. Native behavior remains
covered by the real-machine acceptance tests.
"""

from __future__ import annotations

import dataclasses
import logging

import numpy as np
import pytest

from stenographer.lib.audio.records import CaptureStats
from stenographer.lib.config.models import Config
from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.lib.daemon.daemon import Daemon
from stenographer.lib.daemon.feedback import _play_cue
from stenographer.lib.daemon.pipeline import UtterancePipeline
from stenographer.lib.delivery.timings import DeliveryTimings
from stenographer.lib.logging.utterance_filter import UtteranceFilter
from stenographer.lib.platform.errors import UnsupportedPlatformError
from stenographer.lib.transcribe.results import TranscriptionResult
from stenographer.lib.transcribe.worker_timings import WorkerTimings

# Never a substring of any field name, level, subsystem, or path in the log.
CANARY = "supercalifragilisticexpialidocious"

_RATE = 16000
_SPEECH = np.full(_RATE, 0.02, dtype=np.float32)
_SILENCE = np.zeros(_RATE, dtype=np.float32)
_CAPTURE = CaptureStats(
    activate_ms=3.0,
    capture_seconds=1.0,
    input_frames=_RATE,
    output_frames=_RATE,
    overflow=False,
    capped=False,
)


def _build_or_skip(cfg):
    """Build for real, or skip where the host provides no hotkey/paste backend.

    Expressed as a capability rather than an OS name so a provider that grows
    a real backend starts running these checks without touching the test.
    """
    from stenographer.lib.daemon.daemon import Daemon

    try:
        return Daemon.build(cfg, clipboard_backend="wl-copy")
    except UnsupportedPlatformError as exc:
        pytest.skip(f"no hotkey/injection backend on this host: {exc}")


class _Feedback:
    def __init__(self) -> None:
        self.cues: list[str] = []

    def play(self, name: str) -> None:
        self.cues.append(name)

    def close(self) -> None: ...


class _Notifier:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def info(self, message: str) -> None: ...


class _Recorder:
    def __init__(self, samples: np.ndarray) -> None:
        self._samples = samples
        self.last_capture: CaptureStats | None = None

    def start(self) -> None:
        self.last_capture = None

    def stop(self) -> np.ndarray:
        self.last_capture = _CAPTURE
        return self._samples

    def prepare(self) -> None: ...

    def close(self) -> None: ...


class _Worker:
    def __init__(self, result: TranscriptionResult | None, error: Exception | None) -> None:
        self._result = result
        self._error = error
        self.last_timings: WorkerTimings | None = None
        self.utterances: list[int | None] = []
        self.is_model_ready = False

    def hold_model(self) -> None: ...

    def release_model(self) -> None: ...

    def warmup(self, utterance: int | None = None) -> None: ...

    def shutdown(self) -> None: ...

    def transcribe(self, samples: np.ndarray, utterance: int | None = None) -> TranscriptionResult:
        self.utterances.append(utterance)
        if self._error is not None:
            raise self._error
        self.last_timings = WorkerTimings(lock_wait_ms=0.5, load_ms=900.0, decode_ms=1500.0)
        self.is_model_ready = True
        return self._result


class _Deliverer:
    def __init__(self) -> None:
        self.delivered: list[str] = []
        self.last_timings: DeliveryTimings | None = None

    def deliver(self, text: str, *, on_copied=None, cancelled=None) -> bool:
        self.delivered.append(text)
        self.last_timings = DeliveryTimings(
            copy_ms=8.0, release_wait_ms=30.0, release_timeout=False
        )
        return True

    def close(self) -> None: ...


def _daemon(*, result=None, error=None, samples=_SPEECH, mode="hold") -> Daemon:
    cfg = Config.defaults()
    cfg = dataclasses.replace(cfg, hotkey=dataclasses.replace(cfg.hotkey, mode=mode))
    daemon = Daemon(
        cfg=cfg,
        feedback=_Feedback(),
        notifier=_Notifier(),
        worker=_Worker(result, error),
        recorder=_Recorder(samples),
    )
    daemon._deliverer = _Deliverer()
    daemon._pipeline = UtterancePipeline(
        min_speech_rms=cfg.audio.min_speech_rms,
        worker=daemon._worker,
        deliverer=daemon._deliverer,
        telemetry=daemon._telemetry,
        publish_state=daemon._publish_state,
        fail=daemon._fail,
        play_cue=lambda name: _play_cue(daemon._feedback, name),
        cancelled=daemon._stop_event.is_set,
    )
    return daemon


def _run_utterance(daemon: Daemon) -> None:
    daemon.on_key_down()
    daemon.on_key_up()
    thread = daemon._pipeline_thread
    if thread is not None:
        thread.join(timeout=10.0)
        assert not thread.is_alive()


def _summary(caplog) -> str:
    lines = [m for m in caplog.messages if m.startswith("pipeline: utterance ")]
    assert len(lines) == 1, caplog.messages
    return lines[0]


def _current_stamp() -> str:
    """What ``UtteranceFilter`` would stamp on a record emitted right now."""
    record = logging.getLogger("stenographer.lib.daemon").makeRecord(
        "stenographer.lib.daemon", logging.INFO, __file__, 0, "probe: stamp", (), None
    )
    UtteranceFilter().filter(record)
    return record.utt_suffix


class _Status:
    """Records every lifecycle state the daemon hands to the pill, in order."""

    def __init__(self) -> None:
        self.states: list[OverlayState] = []

    def publish(self, state: OverlayState) -> int:
        self.states.append(state)
        return len(self.states)

    def loading_activity(self, active: bool) -> None: ...


def _daemon_with_status(*, result=None, samples=_SPEECH, warm=True) -> tuple[Daemon, _Status]:
    daemon = _daemon(result=result, samples=samples)
    daemon._worker.is_model_ready = warm
    status = _Status()
    daemon._status = status
    return daemon, status
