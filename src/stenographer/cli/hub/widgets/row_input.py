# SPDX-License-Identifier: GPL-3.0-or-later
"""An input that fits on one row, inside a row of other widgets."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.widgets import Input


def fit_input_to_row(field: Input) -> None:
    """Remove the border and padding of ``field`` and make it one row tall.

    Inline styles: the app stylesheet gives each Input a border and outranks screen
    CSS. With that border, a one-row input has no row left for its text.
    """
    field.styles.border = ("none", "black")
    field.styles.height = 1
    field.styles.padding = 0
