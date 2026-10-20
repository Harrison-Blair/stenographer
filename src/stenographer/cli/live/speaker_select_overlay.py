# SPDX-License-Identifier: GPL-3.0-or-later
"""Render the active speaker choice without a background fill."""

from __future__ import annotations

from rich.text import Text
from textual.widgets._select import SelectOverlay

from stenographer.cli.shared.speaker_colors import speaker_color


class SpeakerSelectOverlay(SelectOverlay):
    """Add an accent marker to the highlighted speaker option."""

    def __init__(self, speakers: tuple[tuple[str, str], ...], **kwargs) -> None:
        super().__init__(**kwargs)
        self._speakers = speakers

    def on_option_list_option_highlighted(self, event: SelectOverlay.OptionHighlighted) -> None:
        speaker_ids = tuple(speaker_id for speaker_id, _label in self._speakers)
        for index, (speaker_id, label) in enumerate(self._speakers, start=1):
            color = speaker_color(speaker_id, speaker_ids)
            prompt = Text()
            if event.option_index == index:
                prompt.append("▶ ", style="bold #5fd7ff")
            else:
                prompt.append("  ")
            prompt.append(label, style=f"bold {color}")
            self.replace_option_prompt_at_index(index, prompt)
        event.stop()
