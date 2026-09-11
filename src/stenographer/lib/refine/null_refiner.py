# SPDX-License-Identifier: GPL-3.0-or-later
"""The refiner the daemon holds when the stage is switched off."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stenographer.lib.refine.results import RefineResult


class NullRefiner:
    """Delivers the transcript untouched and never touches the network.

    The pipeline always has a refiner, so the disabled case is an object rather
    than a ``None`` check at the one place that would otherwise have to
    remember it. ``last_result`` stays ``None`` so a disabled daemon records no
    refine measurements at all, rather than a run of zeroes.
    """

    @property
    def last_result(self) -> RefineResult | None:
        return None

    def will_refine(self, text: str) -> bool:
        return False

    def refine(self, text: str) -> str:
        return text
