# SPDX-License-Identifier: GPL-3.0-or-later
"""Render live session panels and transcript layouts for the hub."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Digits, Static

from stenographer.cli.shared.speaker_colors import speaker_color

if TYPE_CHECKING:
    from stenographer.lib.live.live_session import LiveSession


class LiveView(Vertical):
    """Show the Live panels and a mixed or split transcript."""

    def compose(self) -> ComposeResult:
        with Horizontal(id="live-top"):
            with Vertical(id="live-rec"):
                yield Static("", id="live-rec-status", markup=False)
                yield Digits("", id="live-elapsed")
            yield Static("", id="live-mic", markup=False)
            yield Static("", id="live-system", markup=False)
        yield Static("", id="live-transcript", markup=False)

    def refresh_view(
        self,
        session: LiveSession | None,
        *,
        mic_device: str,
        split: bool,
        recording_active: bool = False,
    ) -> None:
        """Update panel contents from the current session state."""
        if not self.is_mounted:
            return

        elapsed = session.elapsed_seconds if session is not None else 0
        active = session is not None or recording_active
        rec_status = "● REC" if active else "○ REC"
        if session is not None and session.paused:
            rec_status = "Ⅱ PAUSED"
        rec = self.query_one("#live-rec", Vertical)
        rec.border_title = "REC"
        self.query_one("#live-rec-status", Static).update(Text(rec_status, style="bold #ff875f"))
        self.query_one("#live-elapsed", Digits).update(self._format_time(elapsed))

        for key, source, device, color in (
            ("m", "mic", mic_device, "#5fd7ff"),
            ("s", "system", "Default output monitor", "#ffaf5f"),
        ):
            source_state = session.source_states[source] if session is not None else "off"
            level = session.levels_dbfs[source] if session is not None else float("-inf")
            floor = session.meter_floor_dbfs if session is not None else -70.0
            reason = session.source_reasons[source] if session is not None else None
            level_text = "-inf" if not math.isfinite(level) else f"{level:.0f}"
            panel_widget = self.query_one(f"#live-{source}", Static)
            heading = f"[{key}] {source.upper()}"
            state_device = f" {source_state} · "
            panel_width = panel_widget.region.width or max(1, (self.app.size.width - 30) // 3)
            device_width = max(1, panel_width - 4 - len(heading) - len(state_device))
            if len(device) > device_width:
                shortened = device[: device_width - 1].rsplit(" ", 1)[0].rstrip()
                display_device = (shortened or device[: device_width - 1].rstrip()) + "…"
            else:
                display_device = device
            panel = Text()
            panel.append(heading, style=f"bold {color}")
            panel.append(state_device + display_device)
            if reason:
                panel.append(f"\n{reason}")
            panel.append("\n")
            panel.append(
                self._waveform_meter(level, floor, active=source_state == "on"), style=color
            )
            panel.append(f"\n{level_text} dBFS")
            panel_widget.update(panel)

        lines = (
            tuple(sorted(session.lines, key=lambda line: line.start)) if session is not None else ()
        )
        speakers = session.speakers if session is not None else ()
        speaker_count = len(speakers)
        speaker_label = "speaker" if speaker_count == 1 else "speakers"
        transcript = self.query_one("#live-transcript", Static)
        view = "split" if split else "mixed"
        transcript.border_title = f"transcript · {view} · {speaker_count} {speaker_label}"
        speaker_ids = tuple(speaker_id for speaker_id, _label in speakers)
        table = (
            self._split_table(lines, speaker_ids)
            if split
            else self._mixed_table(lines, speaker_ids)
        )
        if not lines:
            message = (
                "Recording is active. Change sections without stopping it."
                if recording_active
                else "Press space to start recording."
                if session is None
                else ""
            )
            content = Group(table, Text(message)) if split else Text(message)
        else:
            content = table
        transcript.update(content)

    @staticmethod
    def _mixed_table(lines, speaker_ids: tuple[str, ...]) -> Table:
        table = Table.grid(padding=(0, 1), expand=True)
        table.add_column(width=8, no_wrap=True)
        table.add_column(no_wrap=True)
        table.add_column(ratio=1)
        for line in lines:
            color = speaker_color(line.speaker_id, speaker_ids, source=line.source)
            label = Text(line.label, style=f"bold {color}")
            text = line.text.replace("\n", " ")
            table.add_row(LiveView._format_time(line.start), label, text)
        return table

    @staticmethod
    def _split_table(lines, speaker_ids: tuple[str, ...]) -> Table:
        table = Table.grid(padding=(0, 1), expand=True)
        table.add_column(width=8, no_wrap=True)
        table.add_column(ratio=1)
        table.add_column(ratio=1)
        mic_heading = Text("MIC · what you said", style="bold #5fd7ff")
        system_heading = Text("SYSTEM · everyone else", style="bold #ffaf5f")
        table.add_row("", mic_heading, system_heading)
        for line in lines:
            color = speaker_color(line.speaker_id, speaker_ids, source=line.source)
            label = Text(line.label, style=f"bold {color}")
            cell = Text()
            cell.append_text(label)
            cell.append(f"  {line.text.replace(chr(10), ' ')}")
            mic = cell if line.source == "mic" else Text("·")
            system = cell if line.source == "system" else Text("·")
            table.add_row(LiveView._format_time(line.start), mic, system)
        return table

    @staticmethod
    def _waveform_meter(level_dbfs: float, floor_dbfs: float, *, active: bool) -> str:
        """Show a waveform-shaped meter whose height follows the input level."""
        if not active or not math.isfinite(level_dbfs):
            return "·" * 17
        height = min(7, max(0, int((level_dbfs - floor_dbfs) / (-10.0 - floor_dbfs) * 7)))
        wave = (1, 2, 3, 5, 7, 6, 5, 3, 2, 1, 1, 2, 3, 5, 6, 5, 3)
        glyphs = "▁▂▃▄▅▆▇"
        bars = (min(height, max(1, round(value / 7 * height))) for value in wave)
        return "".join(glyphs[bar - 1] if bar else "·" for bar in bars)

    @staticmethod
    def _format_time(seconds: float | int) -> str:
        whole_seconds = max(0, int(seconds))
        hours, remainder = divmod(whole_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
