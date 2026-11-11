# SPDX-License-Identifier: GPL-3.0-or-later
"""PipeWire default-output capture for Linux."""

from __future__ import annotations

import shutil
import subprocess
import threading
import time

from stenographer.lib.platform.errors import SystemAudioCaptureError
from stenographer.lib.platform.linux.pw_record import (
    RATE,
    PwRecordDecoder,
    discard_pending,
    read_stdout,
    terminate_process,
)
from stenographer.lib.platform.linux.system_audio_links import (
    has_sink_monitor_links,
    link_inspector,
    parse_pw_dump_output,
    parse_pw_link_output,
)
from stenographer.lib.platform.system_audio import SystemAudioBlockCallback

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
            str(RATE),
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

        decoder = PwRecordDecoder()
        try:
            self._wait_for_sink_monitor(process, sink, inspector)
            try:
                discard_pending(process, decoder)
            except OSError as exc:
                raise SystemAudioCaptureError(
                    "could not discard audio captured before system link verification"
                ) from exc
        except SystemAudioCaptureError:
            terminate_process(process)
            if process.stdout is not None:
                process.stdout.close()
            raise

        self._stopping.clear()
        self._process = process
        self._thread = threading.Thread(
            target=read_stdout,
            args=(process, decoder, on_block, self._stopping, SystemAudioCaptureError),
            daemon=True,
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

    def stop(self) -> None:
        process = self._process
        if process is None:
            return
        self._stopping.set()
        terminate_process(process)
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
