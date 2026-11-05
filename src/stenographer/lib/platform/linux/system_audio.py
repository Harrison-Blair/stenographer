# SPDX-License-Identifier: GPL-3.0-or-later
"""PipeWire default-output capture for Linux."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time

import numpy as np

from stenographer.lib.platform.errors import SystemAudioCaptureError
from stenographer.lib.platform.linux.system_audio_links import (
    has_sink_monitor_links,
    link_inspector,
    parse_pw_dump_output,
    parse_pw_link_output,
)
from stenographer.lib.platform.system_audio import SystemAudioBlockCallback

_RATE = 16000
_BLOCK_FRAMES = 512
_LINK_CHECK_TIMEOUT = 2.0
_LINK_CHECK_INTERVAL = 0.1


class LinuxSystemAudioCapture:
    """Read raw float32 frames from the PipeWire default sink monitor."""

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()

    def _prerequisites(self) -> tuple[str, tuple[str, str], str]:
        """Return pw-record, the link inspector, and the default sink, or raise why not."""
        executable = shutil.which("pw-record")
        if executable is None:
            raise SystemAudioCaptureError("pw-record is not installed")
        inspector = link_inspector()
        if inspector is None:
            raise SystemAudioCaptureError(
                "pw-link and pw-dump are not installed; cannot verify system capture routing"
            )
        return executable, inspector, self._default_sink()

    def available(self) -> tuple[bool, str | None]:
        try:
            self._prerequisites()
        except SystemAudioCaptureError as exc:
            return False, str(exc)
        return True, None

    def start(self, on_block: SystemAudioBlockCallback) -> None:
        if self._process is not None:
            raise SystemAudioCaptureError("system audio capture is already running")
        executable, inspector, sink = self._prerequisites()
        command = [
            executable,
            "-P",
            "{ stream.capture.sink = true, node.name = stenographer-system-capture }",
            "--target",
            sink,
            "--rate",
            str(_RATE),
            "--channels",
            "1",
            "--format",
            "f32",
            "-",
        ]
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
        except OSError as exc:
            raise SystemAudioCaptureError("could not start pw-record") from exc

        try:
            self._wait_for_sink_monitor(process, sink, inspector)
            try:
                self._discard_pending_audio(process)
            except OSError as exc:
                raise SystemAudioCaptureError(
                    "could not discard audio captured before system link verification"
                ) from exc
        except SystemAudioCaptureError:
            self._terminate_process(process)
            if process.stdout is not None:
                process.stdout.close()
            raise

        self._stopping.clear()
        self._process = process
        self._thread = threading.Thread(
            target=self._read_stdout, args=(process, on_block), daemon=True
        )
        self._thread.start()

    def _wait_for_sink_monitor(
        self, process: subprocess.Popen, sink: str, inspector: tuple[str, str]
    ) -> None:
        kind, executable = inspector
        deadline = time.monotonic() + _LINK_CHECK_TIMEOUT
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise SystemAudioCaptureError("pw-record exited before system capture connected")
            remaining = deadline - time.monotonic()
            command = [executable, "-l"] if kind == "pw-link" else [executable]
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=min(remaining, 0.5),
                )
                if kind == "pw-link":
                    ports, links = parse_pw_link_output(result.stdout)
                else:
                    ports, links = parse_pw_dump_output(result.stdout)
                if has_sink_monitor_links(ports, links, sink):
                    return
            except (OSError, subprocess.SubprocessError):
                pass
            time.sleep(min(_LINK_CHECK_INTERVAL, max(0.0, deadline - time.monotonic())))
        raise SystemAudioCaptureError("system capture is not linked to the sink monitor")

    @staticmethod
    def _discard_pending_audio(process: subprocess.Popen) -> None:
        assert process.stdout is not None
        file_descriptor = process.stdout.fileno()
        os.set_blocking(file_descriptor, False)
        try:
            while True:
                try:
                    if not os.read(file_descriptor, 65536):
                        break
                except BlockingIOError:
                    break
        finally:
            os.set_blocking(file_descriptor, True)

    @staticmethod
    def _terminate_process(process: subprocess.Popen) -> None:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    def stop(self) -> None:
        process = self._process
        if process is None:
            return
        self._stopping.set()
        self._terminate_process(process)
        if self._thread is not None:
            self._thread.join()
        if process.stdout is not None:
            process.stdout.close()
        self._process = None

    def _default_sink(self) -> str:
        pactl = shutil.which("pactl")
        if pactl is None:
            raise SystemAudioCaptureError("pactl is not installed")
        try:
            result = subprocess.run(
                [pactl, "get-default-sink"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SystemAudioCaptureError("pactl could not get the default sink") from exc
        sink = result.stdout.strip()
        if not sink:
            raise SystemAudioCaptureError("pactl get-default-sink returned no sink name")
        return sink

    def _read_stdout(self, process: subprocess.Popen, on_block: SystemAudioBlockCallback) -> None:
        assert process.stdout is not None
        pending = bytearray()
        read_error: SystemAudioCaptureError | None = None
        try:
            while True:
                chunk = process.stdout.read(_BLOCK_FRAMES * 4)
                if not chunk:
                    break
                pending.extend(chunk)
                full_bytes = len(pending) - len(pending) % 4
                while full_bytes >= _BLOCK_FRAMES * 4:
                    self._emit(on_block, pending[: _BLOCK_FRAMES * 4])
                    del pending[: _BLOCK_FRAMES * 4]
                    full_bytes -= _BLOCK_FRAMES * 4
            if len(pending) % 4:
                read_error = SystemAudioCaptureError(
                    "pw-record ended in the middle of a float32 sample"
                )
            elif pending:
                self._emit(on_block, pending)
        except OSError:
            read_error = SystemAudioCaptureError("could not read pw-record audio")

        if read_error is not None:
            self._report_error(on_block, read_error)
        elif not self._stopping.is_set():
            status = process.wait()
            self._report_error(
                on_block,
                SystemAudioCaptureError(f"pw-record exited unexpectedly with status {status}"),
            )

    @staticmethod
    def _emit(on_block: SystemAudioBlockCallback, raw: bytes | bytearray) -> None:
        block = np.frombuffer(raw, dtype=np.float32).copy()
        try:
            on_block(block)
        except Exception:
            return

    @staticmethod
    def _report_error(on_block: SystemAudioBlockCallback, error: SystemAudioCaptureError) -> None:
        try:
            on_block(error)
        except Exception:
            return
