# SPDX-License-Identifier: GPL-3.0-or-later
"""The clipboard snapshot reader and restorer, against recording stand-in tools.

Nothing patches ``subprocess``: each test puts executable stand-ins named
``wl-paste``, ``wl-copy`` and ``xclip`` on ``PATH``. They are real processes
behind real pipes, so the bounded read, the deadline and the kill run for
real, and every argv they were given is recorded for an exact comparison. The
real tools are exercised by the opt-in ``test_clipboard_restore_smoke.py``.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time

import pytest

from stenographer.lib.platform.clipboard_snapshot import ClipboardSnapshot
from stenographer.lib.platform.linux import clipboard
from stenographer.lib.platform.linux.clipboard import (
    clipboard_read_available,
    pick_snapshot_type,
    read_clipboard,
    read_clipboard_x11,
    reader_for_backend,
    restore_clipboard,
    restore_clipboard_x11,
    restorer_for_backend,
)
from stenographer.lib.platform.linux.clipboard_backend import ClipboardBackend

_LOGGER = "stenographer.lib.platform.linux.clipboard"
SENTINEL = b"supercalifragilisticexpialidocious"

#: One stand-in for every tool: it records its argv (and its stdin, for a
#: write) and answers from ``tool.json`` beside it.
_TOOL = """\
import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
cfg = json.load(open(os.path.join(here, "tool.json")))
argv = [os.path.basename(sys.argv[0]), *sys.argv[1:]]
stdin = b"" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.buffer.read()
with open(os.path.join(here, "calls.jsonl"), "a") as log:
    log.write(json.dumps({"argv": argv, "stdin": stdin.decode("latin-1")}) + "\\n")
listing = "-l" in argv or "TARGETS" in argv
out = "\\n".join(cfg["types"]).encode() + b"\\n" if listing else cfg["payload"].encode("latin-1")
sys.stdout.buffer.write(out[: cfg.get("partial", len(out))])
sys.stdout.flush()
if cfg.get("hang") == ("list" if listing else "read"):
    time.sleep(30)
sys.exit(cfg.get("status", 0))
"""


class Tools:
    """The stand-in tools on ``PATH`` and what they recorded."""

    def __init__(self, path) -> None:
        self.path = path

    def configure(self, *, types, payload=b"", status=0, hang=None, partial=None) -> None:
        cfg = {"types": types, "payload": payload.decode("latin-1"), "status": status}
        if hang is not None:
            cfg["hang"] = hang
        if partial is not None:
            cfg["partial"] = partial
        (self.path / "tool.json").write_text(json.dumps(cfg))

    @property
    def calls(self) -> list[dict]:
        log = self.path / "calls.jsonl"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text().splitlines()]

    @property
    def argvs(self) -> list[list[str]]:
        return [call["argv"] for call in self.calls]


@pytest.fixture
def tools(tmp_path, monkeypatch) -> Tools:
    script = f"#!{sys.executable}\n{_TOOL}"
    for name in ("wl-paste", "wl-copy", "xclip"):
        tool = tmp_path / name
        tool.write_text(script)
        tool.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    stand_ins = Tools(tmp_path)
    stand_ins.configure(types=["text/plain;charset=utf-8"], payload=b"seed")
    return stand_ins


# --- type choice (pure) -----------------------------------------------------


def test_utf8_plain_text_is_preferred_over_everything_else():
    offered = ["text/html", "text/plain", "text/plain;charset=utf-8", "UTF8_STRING"]
    assert pick_snapshot_type(offered) == "text/plain;charset=utf-8"


def test_plain_text_is_preferred_over_the_first_offered_type():
    assert pick_snapshot_type(["image/png", "text/plain"]) == "text/plain"


def test_otherwise_the_first_offered_type_is_kept():
    assert pick_snapshot_type(["image/png", "text/html"]) == "image/png"


def test_x_selection_atoms_are_never_chosen():
    offered = ["TARGETS", "TIMESTAMP", "MULTIPLE", "SAVE_TARGETS", "image/png"]
    assert pick_snapshot_type(offered) == "image/png"


def test_x_text_atoms_are_only_a_fallback():
    assert pick_snapshot_type(["TARGETS", "UTF8_STRING", "text/html"]) == "text/html"
    assert pick_snapshot_type(["TARGETS", "STRING", "UTF8_STRING"]) == "UTF8_STRING"


def test_nothing_offered_is_no_type():
    assert pick_snapshot_type([]) is None
    assert pick_snapshot_type(["TARGETS", "TIMESTAMP", ""]) is None


# --- exact argv (R7a) ------------------------------------------------------


def test_the_wayland_reader_lists_then_reads_the_chosen_type(tools):
    tools.configure(types=["text/html", "text/plain;charset=utf-8"], payload=b"seed")

    snapshot = read_clipboard()

    assert snapshot == ClipboardSnapshot("text/plain;charset=utf-8", b"seed")
    assert tools.argvs == [
        ["wl-paste", "-l"],
        ["wl-paste", "-n", "-t", "text/plain;charset=utf-8"],
    ]


def test_the_x11_reader_lists_targets_then_reads_the_chosen_type(tools):
    tools.configure(types=["TARGETS", "TIMESTAMP", "UTF8_STRING", "text/plain"], payload=b"x")

    snapshot = read_clipboard_x11()

    assert snapshot == ClipboardSnapshot("text/plain", b"x")
    assert tools.argvs == [
        ["xclip", "-selection", "clipboard", "-o", "-t", "TARGETS"],
        ["xclip", "-selection", "clipboard", "-o", "-t", "text/plain"],
    ]


def test_the_wayland_restorer_writes_the_clipboard_only_with_its_type(tools):
    assert restore_clipboard(ClipboardSnapshot("image/png", b"\x89PNG")) is True

    assert tools.argvs == [["wl-copy", "-t", "image/png"]]
    assert tools.calls[0]["stdin"].encode("latin-1") == b"\x89PNG"


def test_the_x11_restorer_writes_the_clipboard_only_with_its_type(tools):
    assert restore_clipboard_x11(ClipboardSnapshot("text/plain", b"seed")) is True

    assert tools.argvs == [["xclip", "-selection", "clipboard", "-t", "text/plain"]]
    assert tools.calls[0]["stdin"] == "seed"


def test_the_writers_still_write_both_selections(tools):
    assert clipboard.copy_both_selections("hello") is True
    assert tools.argvs == [["wl-copy"], ["wl-copy", "--primary"]]


def test_a_failing_restore_returns_false(tools, caplog):
    tools.configure(types=[], status=1)

    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        assert restore_clipboard(ClipboardSnapshot("text/plain", SENTINEL)) is False

    assert "deliver: restore_failed" in caplog.text
    assert SENTINEL.decode() not in caplog.text


def test_a_missing_restore_tool_returns_false(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert restore_clipboard(ClipboardSnapshot("text/plain", b"seed")) is False
    assert restore_clipboard_x11(ClipboardSnapshot("text/plain", b"seed")) is False


# --- bounds and failures -----------------------------------------------------


def test_a_password_manager_hint_skips_the_snapshot(tools, caplog):
    tools.configure(types=["text/plain", "x-kde-passwordManagerHint"], payload=SENTINEL)

    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        assert read_clipboard() is None
        assert read_clipboard_x11() is None

    assert len(tools.argvs) == 2  # the two listings, never a read
    assert caplog.text.count("deliver: snapshot_skipped reason=sensitive") == 2


def test_an_empty_type_list_is_no_snapshot(tools):
    tools.configure(types=[])
    assert read_clipboard() is None
    assert tools.argvs == [["wl-paste", "-l"]]


def test_an_empty_payload_is_no_snapshot(tools):
    tools.configure(types=["text/plain"], payload=b"")
    assert read_clipboard() is None


def test_a_listing_that_fails_is_no_snapshot(tools):
    tools.configure(types=["text/plain"], status=1)
    assert read_clipboard() is None
    assert tools.argvs == [["wl-paste", "-l"]]


def test_a_missing_reader_is_no_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert read_clipboard() is None
    assert read_clipboard_x11() is None


def test_a_payload_over_the_cap_is_no_snapshot_and_never_logged(tools, monkeypatch, caplog):
    monkeypatch.setattr(clipboard, "_SNAPSHOT_MAX_BYTES", len(SENTINEL) - 1)
    tools.configure(types=["text/plain"], payload=SENTINEL)

    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        assert read_clipboard() is None

    assert "reason=too_large" in caplog.text
    assert SENTINEL.decode() not in caplog.text


def test_the_reader_never_reads_more_than_one_byte_past_the_cap(tools, monkeypatch):
    cap = 10
    monkeypatch.setattr(clipboard, "_SNAPSHOT_MAX_BYTES", cap)
    tools.configure(types=["text/plain"], payload=SENTINEL)
    read = []

    class CountingOs:
        def __getattr__(self, name):
            return getattr(os, name)

        def read(self, fd, n):
            chunk = os.read(fd, n)
            read.append(len(chunk))
            return chunk

    monkeypatch.setattr(clipboard, "os", CountingOs())
    assert clipboard._capture_bounded(["wl-paste", "-n"], time.monotonic() + 5) is None

    assert 0 < sum(read) <= cap + 1


def test_a_payload_at_the_cap_is_kept(tools, monkeypatch):
    monkeypatch.setattr(clipboard, "_SNAPSHOT_MAX_BYTES", len(SENTINEL))
    tools.configure(types=["text/plain"], payload=SENTINEL)

    assert read_clipboard() == ClipboardSnapshot("text/plain", SENTINEL)


def test_an_owner_that_never_finishes_is_cut_off_within_the_budget(tools, monkeypatch, caplog):
    import time

    monkeypatch.setattr(clipboard, "_SNAPSHOT_BUDGET_SECONDS", 0.5)
    tools.configure(types=["text/plain"], payload=SENTINEL, hang="read", partial=5)

    started = time.monotonic()
    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        assert read_clipboard() is None
    elapsed = time.monotonic() - started

    assert elapsed < 2.0
    assert "reason=timeout" in caplog.text
    assert SENTINEL[:5].decode() not in caplog.text


def test_the_budget_covers_the_listing_and_the_read_together(tools, monkeypatch, caplog):
    import time

    monkeypatch.setattr(clipboard, "_SNAPSHOT_BUDGET_SECONDS", 0.5)
    tools.configure(types=["text/plain"], payload=SENTINEL, hang="list")

    started = time.monotonic()
    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        assert read_clipboard_x11() is None

    assert time.monotonic() - started < 2.0
    assert "reason=timeout" in caplog.text
    assert len(tools.argvs) == 1


def test_a_failed_read_with_output_never_logs_the_output(tools, caplog):
    tools.configure(types=["text/plain"], payload=SENTINEL, status=3)

    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        assert read_clipboard() is None

    assert SENTINEL.decode() not in caplog.text


def test_a_snapshot_repr_never_shows_its_bytes():
    snapshot = ClipboardSnapshot("text/plain", SENTINEL)
    assert SENTINEL.decode() not in repr(snapshot)
    assert "text/plain" in repr(snapshot)


# --- wiring ------------------------------------------------------------------


def test_each_backend_maps_to_its_reader_and_restorer(tools):
    assert reader_for_backend(ClipboardBackend.WL_COPY) is read_clipboard
    assert reader_for_backend(ClipboardBackend.X11) is read_clipboard_x11
    assert restorer_for_backend(ClipboardBackend.WL_COPY) is restore_clipboard
    assert restorer_for_backend(ClipboardBackend.X11) is restore_clipboard_x11


def test_no_reader_without_its_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert clipboard_read_available(ClipboardBackend.WL_COPY) is False
    assert reader_for_backend(ClipboardBackend.WL_COPY) is None
    assert reader_for_backend(ClipboardBackend.X11) is None

    tool = tmp_path / "wl-paste"
    tool.write_text("#!/bin/sh\nexit 0\n")
    tool.chmod(0o755)
    assert clipboard_read_available(ClipboardBackend.WL_COPY) is True
    assert clipboard_read_available(ClipboardBackend.X11) is False
