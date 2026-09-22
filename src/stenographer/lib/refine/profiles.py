# SPDX-License-Identifier: GPL-3.0-or-later
"""The complete, fixed refinement-profile vocabulary."""

from __future__ import annotations

from enum import StrEnum


class RefineProfile(StrEnum):
    """A built-in editing policy selected by the utterance hotkey."""

    AGENT = "agent"
    GENERAL = "general"

    @classmethod
    def default(cls) -> RefineProfile:
        return cls.AGENT
