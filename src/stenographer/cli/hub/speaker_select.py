# SPDX-License-Identifier: GPL-3.0-or-later
"""Select a speaker with an unfilled highlighted row."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Select
from textual.widgets._select import SelectCurrent

from stenographer.cli.hub.speaker_select_overlay import SpeakerSelectOverlay


class SpeakerSelect(Select[str]):
    """Show speaker choices with a marker on the highlighted option."""

    def __init__(self, speakers: tuple[tuple[str, str], ...], **kwargs) -> None:
        super().__init__(
            ((label, speaker_id) for speaker_id, label in speakers),
            **kwargs,
        )
        self._speakers = speakers

    def compose(self) -> ComposeResult:
        yield SelectCurrent(self.prompt)
        yield SpeakerSelectOverlay(self._speakers, type_to_search=self._type_to_search).data_bind(
            compact=Select.compact
        )
