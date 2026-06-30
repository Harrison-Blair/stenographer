# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-utterance orchestrator that wires all components together."""

from __future__ import annotations

import logging
import queue
import threading
from typing import TYPE_CHECKING, Literal

import numpy as np

if TYPE_CHECKING:
    from stenographer.asr.model import SegmentInfo
    from stenographer.asr.worker import Worker
    from stenographer.audio.capture import Recorder
    from stenographer.audio.feedback import Feedback
    from stenographer.capabilities import Capabilities
    from stenographer.config import Config
    from stenographer.hotkey.listener import HotkeyListener
    from stenographer.notification import DesktopNotification
    from stenographer.output.clipboard import ClipboardManager
    from stenographer.output.inject import Injector

log = logging.getLogger(__name__)


class Session:
    """Orchestrates one utterance: hotkey -> record -> transcribe -> output.

    The session is the single point of state transitions. All
    callbacks from the hotkey listener, the recorder, and the worker
    funnel through session methods protected by ``_lock`` so that a
    key event arriving concurrently with a shutdown signal does not
    race.
    """

    def __init__(
        self,
        *,
        cfg: Config,
        capabilities: Capabilities,
        listener: HotkeyListener,
        recorder: Recorder,
        worker: Worker,
        feedback: Feedback,
        injector: Injector,
        clipboard: ClipboardManager,
        notification: DesktopNotification | None = None,
        one_shot: bool = False,
    ) -> None:
        self._cfg = cfg
        self._caps = capabilities
        self._listener = listener
        self._recorder = recorder
        self._worker = worker
        self._feedback = feedback
        self._injector = injector
        self._clipboard = clipboard
        self._notification = notification
        self._one_shot = one_shot

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._recording = False
        self._utterances_processed = 0

    @property
    def stop_event(self) -> threading.Event:
        return self._stop_event

    @property
    def is_one_shot(self) -> bool:
        return self._one_shot

    def run(self) -> None:
        """Block until stop() is called (e.g. by SIGTERM)."""
        try:
            self._stop_event.wait()
        except KeyboardInterrupt:
            self.stop()

    def stop(self) -> None:
        if not self._stop_event.is_set():
            log.info("session: stop requested")
        self._stop_event.set()
        if self._recorder.is_active:
            try:
                samples = self._recorder.stop()
            except Exception as exc:
                log.error("session: recorder.stop during shutdown failed: %s", exc)
            else:
                self._drain(samples)
        try:
            self._listener.stop(timeout=2.0)
        except Exception as exc:
            log.error("session: listener.stop failed: %s", exc)
        try:
            self._worker.stop(timeout=10.0)
        except Exception as exc:
            log.error("session: worker.stop failed: %s", exc)
        try:
            self._feedback.close()
        except Exception as exc:
            log.error("session: feedback.close failed: %s", exc)
        try:
            self._injector.close()
        except Exception as exc:
            log.error("session: injector.close failed: %s", exc)
        try:
            self._clipboard.close()
        except Exception as exc:
            log.error("session: clipboard.close failed: %s", exc)
        try:
            if self._notification is not None:
                self._notification.hide()
        except Exception as exc:
            log.error("session: notification.hide failed: %s", exc)

    def on_recording_start(self) -> None:
        with self._lock:
            if self._stop_event.is_set():
                return
            if self._recording:
                log.warning("session: on_recording_start while already recording")
                return
            self._recording = True
            try:
                self._recorder.start()
                log.info("session: recording started")
                if self._notification is not None:
                    self._notification.show_listening()
            except Exception as exc:
                self._recording = False
                log.error("session: recorder.start failed: %s", exc)

    def on_recording_stop(self, mode: Literal["ptt", "toggle"]) -> None:
        with self._lock:
            if not self._recording:
                log.warning("session: on_recording_stop with no active recording")
                return
            self._recording = False
            try:
                samples = self._recorder.stop()
            except Exception as exc:
                log.error("session: recorder.stop failed: %s", exc)
                if self._one_shot:
                    self._stop_event.set()
                return
        log.info("session: recording stopped, %d samples captured", samples.shape[0])
        if self._notification is not None:
            self._notification.hide()
        self._process(samples, mode)
        if self._one_shot:
            self._stop_event.set()

    def on_toggle_off(self) -> None:
        self.on_recording_stop("toggle")

    def _process(self, samples: np.ndarray, mode: Literal["ptt", "toggle"]) -> None:
        log.info("session: processing %d samples (mode=%s)", samples.shape[0], mode)

        segment_queue: queue.Queue[SegmentInfo] = queue.Queue()
        future = self._worker.submit(samples, on_segment=segment_queue.put)

        injected_text = ""
        while True:
            try:
                seg = segment_queue.get(timeout=0.1)
            except queue.Empty:
                if future.done():
                    break
                continue
            if seg.text.strip():
                try:
                    self._injector.type_text(seg.text, raw=True)
                except Exception as exc:
                    log.error("session: injector partial failed: %s", exc)
                injected_text += seg.text

        try:
            result = future.result(timeout=5.0)
        except Exception as exc:
            log.error("session: transcription failed: %s", exc)
            return
        self._utterances_processed += 1
        text = result.text
        log.info("session: transcript %r", text)
        if not text or not text.strip():
            log.info("session: empty transcript, skipping output")
            return
        if injected_text.strip() != text.strip() and self._caps.has_wtype:
            try:
                self._injector.type_text(text)
            except Exception as exc:
                log.error("session: injector.type_text raised: %s", exc)
        if self._cfg.clipboard.enabled and self._caps.has_wl_copy:
            try:
                self._clipboard.copy(text)
            except Exception as exc:
                log.error("session: clipboard.copy raised: %s", exc)

    def _drain(self, samples: np.ndarray) -> None:
        log.info("session: draining in-flight utterance on shutdown")
        self._process(samples, "ptt")
