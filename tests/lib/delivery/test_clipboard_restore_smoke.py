# SPDX-License-Identifier: GPL-3.0-or-later
"""Integration smoke for the clipboard history copy and restore, with no chord.

Real wl-copy/wl-paste against the session compositor; the keyboard is a
recording stand-in, so nothing is typed into the focused window. A
``wl-paste --watch`` recorder sees every clipboard change the way a clipboard
history manager does, and keeps only each entry's length and sha256, never
its content. The user's real clipboard is saved through the reader under test
before anything is written and put back afterwards, even on failure.

Side effects: the test tokens pass through any running clipboard history
manager, and the primary selection keeps the last token (primary is never
restored, by design).

Collected only with STENOGRAPHER_INTEGRATION=1, and skipped unless the
detected backend is wl-copy with both wl-copy and wl-paste on PATH.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import time
import uuid

import pytest

from stenographer.lib.delivery.deliverer import Deliverer
from stenographer.lib.platform.clipboard_snapshot import ClipboardSnapshot
from stenographer.lib.platform.linux.clipboard import (
    copy_both_selections,
    detect_clipboard_backend,
    read_clipboard,
    restore_clipboard,
)
from stenographer.lib.platform.linux.clipboard_backend import ClipboardBackend
from stenographer.lib.platform.linux.process import child_env

pytestmark = pytest.mark.integration

if detect_clipboard_backend() is not ClipboardBackend.WL_COPY:
    pytest.skip("the chord-free smoke covers the wl-copy backend", allow_module_level=True)
if shutil.which("wl-copy") is None or shutil.which("wl-paste") is None:
    pytest.skip("wl-copy/wl-paste not on PATH", allow_module_level=True)

#: Appends ``<length> <sha256>`` for each clipboard entry it is handed on stdin.
_RECORDER = """\
import hashlib, sys
data = sys.stdin.buffer.read()
with open(sys.argv[1], "a") as log:
    log.write(f"{len(data)} {hashlib.sha256(data).hexdigest()}\\n")
"""


class RecordingKeyboard:
    def __init__(self) -> None:
        self.chords = 0

    def send_chord(self) -> None:
        self.chords += 1

    def close(self) -> None: ...


def _entry(text: str) -> str:
    data = text.encode("utf-8")
    return f"{len(data)} {hashlib.sha256(data).hexdigest()}"


@pytest.fixture
def real_clipboard():
    """Save the user's clipboard through the reader under test; always put it back."""
    saved = read_clipboard()
    if saved is None:
        pytest.skip("the clipboard holds nothing this reader can save and restore")
    try:
        yield saved
    finally:
        assert restore_clipboard(saved) is True


@pytest.fixture
def history(tmp_path):
    """A ``wl-paste --watch`` recorder; yields a reader of what it has seen."""
    script = tmp_path / "recorder.py"
    script.write_text(_RECORDER)
    log = tmp_path / "history.log"
    log.touch()
    watcher = subprocess.Popen(
        ["wl-paste", "--watch", sys.executable, str(script), str(log)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=child_env(),
    )
    try:
        yield lambda: log.read_text().splitlines()
    finally:
        watcher.terminate()
        watcher.wait(timeout=5.0)


def _wait_for(read, predicate, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        entries = read()
        if predicate(entries):
            return entries
        time.sleep(0.05)
    return read()


def test_history_sees_original_then_refined_then_the_restored_seed(real_clipboard, history):
    token = uuid.uuid4()
    seed = f"stenographer-smoke-seed-{token}"
    original = f"stenographer-smoke-original-{token} "
    refined = f"stenographer-smoke-refined-{token} "
    seed_snapshot = ClipboardSnapshot("text/plain;charset=utf-8", seed.encode())

    assert restore_clipboard(seed_snapshot) is True
    entries = _wait_for(history, lambda e: _entry(seed) in e)
    assert _entry(seed) in entries
    start = len(entries)

    keyboard = RecordingKeyboard()
    deliverer = Deliverer(
        keyboard=keyboard,
        copy=copy_both_selections,
        read=read_clipboard,
        restore=restore_clipboard,
        restore_delay=0.2,
    )
    assert deliverer.deliver(refined, original=original) is True
    assert keyboard.chords == 1
    assert deliverer.restore_clipboard() is True

    expected = [_entry(original), _entry(refined), _entry(seed)]
    entries = _wait_for(history, lambda e: e[start:] == expected)
    assert entries[start:] == expected
    assert read_clipboard() == seed_snapshot
    timings = deliverer.last_timings
    assert timings.original_copied is True
    assert timings.restored is True
