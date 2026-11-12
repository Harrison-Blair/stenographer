# SPDX-License-Identifier: GPL-3.0-or-later
"""PipeWire microphone capture and the PipeWire source list for Linux."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading

from stenographer.lib.platform.errors import MicCaptureError
from stenographer.lib.platform.linux.process import child_env
from stenographer.lib.platform.linux.pw_record import (
    RATE,
    PwRecordDecoder,
    read_stdout,
    terminate_process,
)
from stenographer.lib.platform.mic_capture import InputSource, InputSources, MicBlockCallback

_PACTL_TIMEOUT = 5


class LinuxMicCapture:
    """Read 16 kHz mono float32 from one PipeWire source through a ``pw-record`` child."""

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()

    def start(self, target: str | None, on_block: MicBlockCallback) -> None:
        if self._process is not None:
            raise MicCaptureError("microphone capture is already running")
        executable = shutil.which("pw-record")
        if executable is None:
            raise MicCaptureError("pw-record is not installed")
        try:
            process = subprocess.Popen(
                pw_record_command(executable, target),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
                env=child_env(),
            )
        except OSError as exc:
            raise MicCaptureError("could not start pw-record") from exc
        self._stopping.clear()
        self._process = process
        self._thread = threading.Thread(
            target=read_stdout,
            args=(process, PwRecordDecoder(), on_block, self._stopping, MicCaptureError),
            name="stenographer-mic-capture",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """End the child and return after the reader has delivered its last block."""
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
        self._thread = None


def pw_record_command(executable: str, target: str | None) -> list[str]:
    """The ``pw-record`` command line for *target* (``None``: the default source). PURE.

    A named source that is absent, or that goes away, makes ``pw-record`` exit
    instead of recording another microphone. WirePlumber 0.5 obeys
    ``node.dont-fallback``; WirePlumber 0.4 knows only ``node.dont-reconnect``.
    """
    command = [executable]
    if target is not None:
        properties = "{ node.dont-fallback = true node.dont-reconnect = true }"
        command += ["-P", properties, "--target", target]
    return [*command, "--rate", str(RATE), "--channels", "1", "--format", "f32", "-"]


def parse_pactl_sources(output: str) -> tuple[InputSource, ...]:
    """The microphones in ``pactl -f json list sources`` output; monitors are left out. PURE."""
    items = json.loads(output)
    if not isinstance(items, list):
        raise ValueError("pactl source list is not a JSON list")
    sources = []
    for item in items:
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str) or not name or name.endswith(".monitor"):
            continue
        description = item.get("description")
        sources.append(InputSource(name, description if isinstance(description, str) else name))
    return tuple(sources)


def input_sources() -> InputSources:
    """List the PipeWire sources through ``pactl``; the reason as ``error`` when it cannot.

    Without ``pw-record`` no source can record, so its absence is the error too.
    """
    if shutil.which("pw-record") is None:
        return InputSources(error="pw-record is not installed")
    pactl = shutil.which("pactl")
    if pactl is None:
        return InputSources(error="pactl is not installed")
    try:
        listing = subprocess.run(
            [pactl, "-f", "json", "list", "sources"],
            capture_output=True,
            text=True,
            check=True,
            timeout=_PACTL_TIMEOUT,
            env=child_env(),
        )
        sources = parse_pactl_sources(listing.stdout)
        default = subprocess.run(
            [pactl, "get-default-source"],
            capture_output=True,
            text=True,
            check=True,
            timeout=_PACTL_TIMEOUT,
            env=child_env(),
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return InputSources(error=f"pactl could not list the audio sources: {exc}")
    return InputSources(sources=sources, default=default.stdout.strip() or None)
