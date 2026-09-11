# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging
import sys
import threading
import time
from typing import TYPE_CHECKING

from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.lib.logging.pipeline import log_failure
from stenographer.lib.platform.errors import UnsupportedPlatformError
from stenographer.overlay.helper.control import reduce_helper_control
from stenographer.overlay.helper.models import HelperControlState
from stenographer.overlay.platform import current_platform
from stenographer.overlay.protocol.codec import decode_message, encode_message
from stenographer.overlay.protocol.errors import ProtocolError
from stenographer.overlay.protocol.line_reader import LineReader
from stenographer.overlay.protocol.messages import (
    CommandMessage,
    ProtocolMessage,
)
from stenographer.overlay.spectrum.analysis import DEFAULT_SPECTRUM_FLOOR_DBFS
from stenographer.overlay.spectrum.spectrum_analyzer import SpectrumAnalyzer

if TYPE_CHECKING:
    from stenographer.overlay.platform.helper_process import HelperProcess

from stenographer.overlay.supervision.constants import (
    _READ_SIZE,
    _SHUTDOWN_GRACE_SECONDS,
    _SPECTRUM_INTERVAL,
    _THREAD_JOIN_SECONDS,
    log,
)
from stenographer.overlay.supervision.models import RestartBudget, _ProcessOutcome
from stenographer.overlay.supervision.outbound_mailbox import OutboundMailbox
from stenographer.overlay.supervision.policy import (
    _helper_stderr_path,
    helper_command,
    helper_ready_timed_out,
    schedule_spectrum,
    serve_timeout,
)


class OverlaySupervisor:
    """Nonblocking daemon-side sink backed by one isolated helper process."""

    def __init__(self, spectrum_floor_dbfs: object = DEFAULT_SPECTRUM_FLOOR_DBFS) -> None:
        self._mailbox = OutboundMailbox()
        self._analyzer = SpectrumAnalyzer(spectrum_floor_dbfs)
        self._analyzer_generation: int | None = None
        self._last_analysis_at: float | None = None
        self._thread = threading.Thread(
            target=self._thread_main,
            name="stenographer-overlay-supervisor",
            daemon=True,
        )
        self._thread.start()

    def publish(self, state: OverlayState) -> None:
        self._mailbox.publish(state)

    def loading_activity(self, active: bool) -> None:
        self._mailbox.loading_activity(active)

    def audio_block(self, samples: object, sample_rate: int, stream_epoch: int) -> None:
        self._mailbox.audio_block(samples, sample_rate, stream_epoch)

    def close(self) -> None:
        self._mailbox.close()
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=_THREAD_JOIN_SECONDS)

    def _thread_main(self) -> None:
        budget = RestartBudget(1)
        command = helper_command(sys.executable, frozen=bool(getattr(sys, "frozen", False)))
        try:
            try:
                transport = current_platform().helper_transport()
            except UnsupportedPlatformError:
                log.info("overlay: helper_unavailable reason=unsupported_platform")
                return
            while True:
                self._mailbox.expire_transient()
                try:
                    helper = transport.spawn(command, stderr_path=_helper_stderr_path())
                except (OSError, ValueError) as exc:
                    log.warning("overlay: helper_start_failed error_type=%s", type(exc).__name__)
                    if not budget.on_exit(unexpected=True):
                        return
                    continue

                try:
                    outcome = self._serve(helper)
                except Exception as exc:
                    log.warning("overlay: supervisor_failed error_type=%s", type(exc).__name__)
                    helper.close()
                    self._reap(helper, expected=False)
                    outcome = _ProcessOutcome(False)
                if outcome.unavailable or outcome.expected:
                    return
                if not budget.on_exit(unexpected=True):
                    log.warning("overlay: helper_disabled reason=restart_budget_exhausted")
                    return
                log.warning("overlay: helper_restarting")
        finally:
            self._mailbox.disable()
            self._analyzer.reset()

    def _produce_spectrum(self, now: float) -> None:
        current = self._mailbox.current_state
        if current.state is not OverlayState.RECORDING:
            if self._analyzer_generation is not None:
                self._analyzer_generation = None
                self._last_analysis_at = None
            self._mailbox.take_audio_nowait()
            return
        if self._analyzer_generation != current.generation:
            self._analyzer.begin_recording()
            self._analyzer_generation = current.generation
            self._last_analysis_at = None
        block = self._mailbox.take_audio_nowait()
        if block is None or block.generation != current.generation:
            return
        elapsed = (
            _SPECTRUM_INTERVAL
            if self._last_analysis_at is None
            else max(0.0, now - self._last_analysis_at)
        )
        levels = self._analyzer.update(
            block.samples,
            block.sample_rate,
            stream_epoch=block.stream_epoch,
            elapsed=elapsed,
        )
        self._last_analysis_at = now
        self._mailbox.publish_spectrum(current.generation, levels)

    def _serve(self, helper: HelperProcess) -> _ProcessOutcome:
        reader = LineReader()
        control_state = HelperControlState()
        started_at = time.monotonic()
        expected_exit = False
        next_spectrum_at: float | None = None

        # A restarted helper needs an atomic snapshot even when the original
        # records were already consumed by the previous process.
        for replay in self._mailbox.replay_for_helper():
            if not self._write(helper, replay):
                helper.close()
                self._reap(helper, expected=False)
                return _ProcessOutcome(False)

        try:
            stream_failed = False
            while helper.is_running():
                now = time.monotonic()
                if helper_ready_timed_out(
                    started_at=started_at, now=now, ready=control_state.ready
                ):
                    log.warning("overlay: helper_ready_timeout")
                    break
                self._mailbox.expire_transient()
                recording = self._mailbox.current_state.state is OverlayState.RECORDING
                next_spectrum_at, produce = schedule_spectrum(recording, next_spectrum_at, now)
                if produce:
                    self._produce_spectrum(now)
                message = self._mailbox.take_nowait()
                if message is not None:
                    if not self._write(helper, message):
                        break
                    if isinstance(message, CommandMessage):
                        expected_exit = True
                        helper.close_input()

                timeout = serve_timeout(time.monotonic(), next_spectrum_at)
                if helper.wait_readable(timeout):
                    chunk = helper.read(_READ_SIZE)
                    if not chunk:
                        try:
                            reader.finish()
                        except ProtocolError as exc:
                            log_failure(
                                log,
                                logging.WARNING,
                                "overlay: helper_protocol_error",
                                exc,
                                safe=True,
                                phase="finish",
                            )
                        stream_failed = True
                    else:
                        try:
                            records = reader.feed(chunk)
                            for record in records:
                                control = decode_message(record)
                                transition = reduce_helper_control(control_state, control)
                                control_state = transition.state
                                expected_exit |= control_state.expected_exit
                                stream_failed |= transition.stop
                                if transition.event == "ready":
                                    log.info("overlay: ready backend=%s", transition.value)
                                elif transition.event == "backend_lost":
                                    log.warning("overlay: backend_lost reason=%s", transition.value)
                                else:
                                    log.info("overlay: unavailable reason=%s", transition.value)
                        except ProtocolError as exc:
                            log_failure(
                                log,
                                logging.WARNING,
                                "overlay: helper_protocol_error",
                                exc,
                                safe=True,
                                phase="feed",
                            )
                            stream_failed = True
                if stream_failed:
                    break
                if expected_exit and helper.is_running():
                    break
        finally:
            helper.close()
            self._reap(helper, expected=expected_exit)
        return _ProcessOutcome(expected_exit, control_state.unavailable)

    @staticmethod
    def _write(helper: HelperProcess, message: ProtocolMessage) -> bool:
        try:
            helper.write(encode_message(message).encode("ascii"))
        except (BrokenPipeError, OSError, ProtocolError):
            return False
        return True

    @staticmethod
    def _reap(helper: HelperProcess, *, expected: bool) -> None:
        """Give an expected exit its grace period, then let the host escalate."""
        if expected and helper.is_running():
            helper.wait(_SHUTDOWN_GRACE_SECONDS)
        helper.terminate(_SHUTDOWN_GRACE_SECONDS)
