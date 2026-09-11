# SPDX-License-Identifier: GPL-3.0-or-later
"""The contract the pipeline holds a refiner by."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from stenographer.lib.refine.results import RefineResult


@runtime_checkable
class TextRefiner(Protocol):
    """An optional cleanup pass between formatting and delivery.

    ``refine`` must never raise and must never return an empty string: a
    refiner that cannot do its job returns the text it was given. The pipeline
    asks ``will_refine`` first so it only shows the "Refining" pill for an
    utterance that is really going to a model, and reads ``last_result`` after
    for the numbers the summary line and analytics record.
    """

    @property
    def last_result(self) -> RefineResult | None:
        """The verdict of the most recent :meth:`refine`, or ``None``."""

    def will_refine(self, text: str) -> bool:
        """Whether :meth:`refine` would send *text* to a model. PURE."""

    def refine(self, text: str) -> str:
        """Return the text to deliver: cleaned, or *text* itself on any failure."""
