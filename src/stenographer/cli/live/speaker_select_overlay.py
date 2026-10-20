# SPDX-License-Identifier: GPL-3.0-or-later
"""Render the active speaker choice without a background fill."""

from __future__ import annotations

from rich.text import Text
from textual.widgets._select import SelectOverlay


class SpeakerSelectOverlay(SelectOverlay):
    """Add an accent marker to the highlighted speaker option."""

    def __init__(self, speakers: tuple[tuple[str, str], ...], **kwargs) -> None:
        super().__init__(**kwargs)
        self._speakers = speakers

    def on_option_list_option_highlighted(self, event: SelectOverlay.OptionHighlighted) -> None:
        for index, (_speaker_id, label) in enumerate(self._speakers, start=1):
            prompt = Text()
            if event.option_index == index:
                prompt.append("▶ ", style="bold #5fd7ff")
                prompt.append(label, style="bold #5fd7ff")
            else:
                prompt.append(f"  {label}")
            self.replace_option_prompt_at_index(index, prompt)
        event.stop()
