# SPDX-License-Identifier: GPL-3.0-or-later
"""A real speaker diarizer whose helper process cannot start (as at a process limit)."""

from __future__ import annotations

import errno
import multiprocessing

from stenographer.lib.platform.linux import nemo_diarizer
from stenographer.lib.platform.linux.nemo_diarizer import NemoSpeakerDiarizer

_SPAWN = multiprocessing.get_context("spawn")


class _Unstartable:
    pid = None

    def __init__(self, **_options) -> None:
        pass

    def start(self) -> None:
        raise OSError(errno.EAGAIN, "Resource temporarily unavailable")


class _Context:
    """Real pipes; a process that fails to start. Records the pipes it made."""

    def __init__(self) -> None:
        self.pipes = []

    def Pipe(self, duplex=True):  # noqa: N802 - the multiprocessing name
        ends = _SPAWN.Pipe(duplex=duplex)
        self.pipes.extend(ends)
        return ends

    def Process(self, **options):  # noqa: N802 - the multiprocessing name
        return _Unstartable(**options)


class AvailableDiarizer(NemoSpeakerDiarizer):
    def unavailable_reason(self) -> str | None:
        return None


def unstartable_diarizer(monkeypatch) -> tuple[NemoSpeakerDiarizer, _Context]:
    context = _Context()
    monkeypatch.setattr(nemo_diarizer.multiprocessing, "get_context", lambda _method: context)
    return AvailableDiarizer(), context
