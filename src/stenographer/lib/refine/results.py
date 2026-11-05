# SPDX-License-Identifier: GPL-3.0-or-later
"""What one refine attempt measured, and nothing else.

Deliberately text-free: the refiner hands the deliverable string back from
``refine`` and leaves this record for the log, the summary line, and the
analytics projection, none of which may ever see a transcript. Mirrors the
``WorkerTimings`` / ``DeliveryTimings`` idiom — the collaborator keeps the last
one on ``last_result``.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The model produced text that passed the guard and was delivered.
OUTCOME_APPLIED = "applied"
#: Below ``refine.min_words``; no request was made.
OUTCOME_SKIPPED = "skipped"
#: The time budget elapsed before a reply arrived.
OUTCOME_TIMEOUT = "timeout"
#: Transport, HTTP, or reply-shape failure.
OUTCOME_FAILED = "failed"
#: A well-formed reply the output guard refused, truncation included.
OUTCOME_REJECTED = "rejected"
#: The utterance was cancelled, or the stage shut down, before a reply could be
#: used. Nothing was wrong with the model or the host.
OUTCOME_CANCELLED = "cancelled"


@dataclass(frozen=True)
class RefineResult:
    """One attempt's verdict and its measurements. Never holds any text."""

    outcome: str
    chars_in: int | None = None
    chars_out: int | None = None
    duration_ms: float | None = None

    @property
    def applied(self) -> bool:
        """Whether the delivered text came from the model."""

        return self.outcome == OUTCOME_APPLIED

    @property
    def attempted(self) -> bool:
        """Whether a request was actually sent to the model."""

        # Skipped and cancelled outcomes charge no attempt to the model.
        return self.outcome not in {OUTCOME_SKIPPED, OUTCOME_CANCELLED}

    @property
    def failed(self) -> bool:
        """Whether an attempt was made and did not produce usable text."""

        return self.outcome in {OUTCOME_TIMEOUT, OUTCOME_FAILED, OUTCOME_REJECTED}
