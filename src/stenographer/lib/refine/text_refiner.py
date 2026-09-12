# SPDX-License-Identifier: GPL-3.0-or-later
"""The contract the pipeline holds a refiner by."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from stenographer.lib.refine.cancellation import never_cancelled
from stenographer.lib.refine.results import RefineResult

if TYPE_CHECKING:
    from collections.abc import Callable


@runtime_checkable
class TextRefiner(Protocol):
    """An optional cleanup pass between formatting and delivery.

    ``refine`` must never raise and must never return an empty string: a
    refiner that cannot do its job returns the text it was given. The pipeline
    asks ``will_refine`` first so it only shows the "Refining" pill for an
    utterance that is really going to a model, and reads ``last_result`` after
    for the numbers the summary line and analytics record.

    ``refine`` is also the longest an utterance can be held anywhere, so it
    takes the caller's ``cancelled`` predicate and is expected to stop at the
    next point it cheaply can — the granularity is whatever the implementation
    cannot interrupt, not a promise of immediacy. The parameter has a default
    so a caller with nothing to cancel (``transcribe --refine``) says nothing,
    but it is part of the contract rather than an optional extra: every
    implementer can simply accept it, and a refiner that quietly ignored it
    would strand the daemon for the whole budget.
    """

    @property
    def last_result(self) -> RefineResult | None:
        """The verdict of the most recent :meth:`refine`, or ``None``."""

    def will_refine(self, text: str) -> bool:
        """Whether :meth:`refine` would send *text* to a model. PURE."""

    def refine(self, text: str, *, cancelled: Callable[[], bool] = never_cancelled) -> str:
        """Return the text to deliver: cleaned, or *text* itself on any failure."""
