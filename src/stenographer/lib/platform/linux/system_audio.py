# SPDX-License-Identifier: GPL-3.0-or-later
"""PipeWire default-output capture for Linux."""

from __future__ import annotations

import shutil
import subprocess
import threading

import numpy as np

from stenographer.lib.platform.errors import SystemAudioCaptureError
from stenographer.lib.platform.system_audio import SystemAudioBlockCallback

_RATE = 16000
_BLOCK_FRAMES = 512


class LinuxSystemAudioCapture:
    """Read raw float32 frames from the PipeWire default sink monitor."""

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._callback: SystemAudioBlockCallback | None = None
        self._stopping = threading.Event()

    def available(self) -> tuple[bool, str | None]:
        if shutil.which("pw-record") is None:
            return False, "pw-record is not installed"
        sink, reason = self._default_sink()
        if reason is not None:
            return False, reason
        if not sink:
            return False, "pactl get-default-sink returned no sink name"
        return True, None

    def start(self, on_block: SystemAudioBlockCallback) -> None:
        if self._process is not None:
            raise SystemAudioCaptureError("system audio capture is already running")
        executable = shutil.which("pw-record")
        if executable is None:
            raise SystemAudioCaptureError("pw-record is not installed")
        sink, reason = self._default_sink()
        if reason is not None or not sink:
            raise SystemAudioCaptureError(reason or "pactl returned no default sink")
        command = [
            executable,
            "--raw",
            "--target",
            f"{sink}.monitor",
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

        self._callback = on_block
        self._stopping.clear()
        self._process = process
        self._thread = threading.Thread(target=self._read_stdout, args=(process,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        process = self._process
        if process is None:
            return
        self._stopping.set()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if self._thread is not None:
            self._thread.join()
        if process.stdout is not None:
            process.stdout.close()
        self._process = None
        self._callback = None

    def _default_sink(self) -> tuple[str | None, str | None]:
        pactl = shutil.which("pactl")
        if pactl is None:
            return None, "pactl is not installed"
        try:
            result = subprocess.run(
                [pactl, "get-default-sink"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return None, "pactl could not get the default sink"
        sink = result.stdout.strip()
        if not sink:
            return None, "pactl get-default-sink returned no sink name"
        return sink, None

    def _read_stdout(self, process: subprocess.Popen) -> None:
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
                    self._emit(pending[: _BLOCK_FRAMES * 4])
                    del pending[: _BLOCK_FRAMES * 4]
                    full_bytes -= _BLOCK_FRAMES * 4
            if len(pending) % 4:
                read_error = SystemAudioCaptureError(
                    "pw-record ended in the middle of a float32 sample"
                )
            elif pending:
                self._emit(pending)
        except OSError:
            read_error = SystemAudioCaptureError("could not read pw-record audio")

        if read_error is not None:
            self._report_error(read_error)
        elif not self._stopping.is_set():
            status = process.wait()
            self._report_error(
                SystemAudioCaptureError(f"pw-record exited unexpectedly with status {status}")
            )

    def _emit(self, raw: bytes | bytearray) -> None:
        if self._callback is None:
            return
        block = np.frombuffer(raw, dtype=np.float32).copy()
        try:
            self._callback(block)
        except Exception:
            return

    def _report_error(self, error: SystemAudioCaptureError) -> None:
        if self._callback is not None:
            try:
                self._callback(error)
            except Exception:
                return
