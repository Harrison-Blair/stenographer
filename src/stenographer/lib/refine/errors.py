# SPDX-License-Identifier: GPL-3.0-or-later
"""Refine-domain failures.

None of these ever carries transcript text: the stage fails open, and a message
that quoted the utterance would reach the log through any caller that reported
it. Constructors take a short fixed reason instead.
"""

from __future__ import annotations


class RefineError(Exception):
    """Base for every refine failure. Callers deliver the raw text instead."""


class RefineTransportError(RefineError):
    """The Ollama host could not be reached, or answered with an HTTP error."""


class RefineTimeoutError(RefineError):
    """The time budget for this utterance elapsed before a reply arrived."""


class RefineResponseError(RefineError):
    """The reply was not a usable Ollama chat response."""


class RefineRejectedError(RefineError):
    """The reply parsed, but the output guard refused it."""
