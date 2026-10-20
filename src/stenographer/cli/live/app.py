# SPDX-License-Identifier: GPL-3.0-or-later
"""Textual interface for a live audio session."""

from __future__ import annotations

import asyncio
import math
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from stenographer.cli.live.rename_dialog import RenameDialog
from stenographer.lib.live.live_session import LiveSession
from stenographer.lib.live.transcript_line import TranscriptLine


class LiveApp(App[None]):
    """Display session status, transcript lines, and live controls."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("space", "toggle_pause", "Pause / resume"),
        ("m", "toggle_mic", "Microphone"),
        ("s", "toggle_system", "System audio"),
        ("r", "rename", "Rename speaker"),
        ("q", "stop", "Stop and save"),
        ("ctrl+c", "stop", "Stop and save"),
    ]
    CSS = """
    #status {
        height: auto;
        min-height: 2;
        padding: 0 1;
        background: $boost;
    }
    #transcript-scroll {
        height: 1fr;
        padding: 1 2;
    }
    #transcript {
        width: 1fr;
    }
    #key-hints {
        height: 1;
        padding: 0 1;
        background: $boost;
    }
    """

    def __init__(self, session: LiveSession) -> None:
        super().__init__()
        self._session = session
        self._session.subscribe(self._receive_line)

    def compose(self) -> ComposeResult:
        yield Static("", id="status", markup=False)
        with VerticalScroll(id="transcript-scroll"):
            yield Static("", id="transcript", markup=False)
        yield Static(
            "space pause/resume   m mic   s system   r rename   q stop/save", id="key-hints"
        )

    def on_mount(self) -> None:
        self._session.start()
        self.set_interval(0.1, self._refresh_status)
        self._refresh_status()
        self._refresh_transcript()

    def action_toggle_pause(self) -> None:
        if self._session.paused:
            self._session.resume()
        else:
            self._session.pause()
        self._refresh_status()

    def action_toggle_mic(self) -> None:
        self._session.toggle("mic")
        self._refresh_status()

    def action_toggle_system(self) -> None:
        self._session.toggle("system")
        self._refresh_status()

    def action_rename(self) -> None:
        speakers = self._session.speakers
        if not speakers:
            self.notify("No system speakers are available to rename.")
            return
        self.push_screen(RenameDialog(speakers), self._rename_speaker)

    async def action_stop(self) -> None:
        await asyncio.to_thread(self._session.stop)
        self.exit()

    def _rename_speaker(self, value: tuple[str, str] | None) -> None:
        if value is None:
            return
        speaker_id, name = value
        try:
            self._session.rename(speaker_id, name)
        except ValueError as exc:
            self.notify(str(exc))
            return
        self._refresh_transcript()

    def _receive_line(self, _line: TranscriptLine) -> None:
        self.call_from_thread(self._refresh_transcript)

    def _refresh_transcript(self) -> None:
        rendered = "\n".join(
            f"{self._format_time(line.start)}  {line.label}  {line.text}"
            for line in self._session.lines
        )
        self.query_one("#transcript", Static).update(rendered)

    def _refresh_status(self) -> None:
        elapsed = max(0, int(self._session.elapsed_seconds))
        state = "PAUSED" if self._session.paused else "REC"
        parts = [f"{state} {self._format_time(elapsed)}"]
        for key, source in (("m", "mic"), ("s", "system")):
            source_state = self._session.source_states[source].upper()
            level = self._session.levels_dbfs[source]
            meter = self._format_meter(level)
            level_text = "-inf" if not math.isfinite(level) else f"{level:.0f}"
            reason = self._session.source_reasons[source]
            detail = f"{key} {source_state} [{meter} {level_text} dBFS]"
            if reason:
                detail += f" ({reason})"
            parts.append(detail)
        parts.append(f"{self._session.model_name}  queue {self._session.queue_depth}")
        self.query_one("#status", Static).update("  |  ".join(parts))

    @staticmethod
    def _format_time(seconds: float | int) -> str:
        whole_seconds = max(0, int(seconds))
        hours, remainder = divmod(whole_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    @staticmethod
    def _format_meter(level_dbfs: float) -> str:
        filled = 0 if not math.isfinite(level_dbfs) else min(5, max(0, int((level_dbfs + 60) / 12)))
        return "█" * filled + "·" * (5 - filled)
