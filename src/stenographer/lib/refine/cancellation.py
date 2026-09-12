# SPDX-License-Identifier: GPL-3.0-or-later
"""Who may stop a refine that has already started, and how that is asked.

The predicate itself belongs to the caller — the daemon already owns one cancel
flag for the whole utterance — so this module holds only the default every
refiner falls back to when nobody is watching. Kept out of the refiner because
a file with an ordinary class holds nothing else, and out of the pipeline
because the protocol, both implementations, and the caller all name it.
"""

from __future__ import annotations


def never_cancelled() -> bool:
    """The default predicate: nothing is ever cancelled. PURE.

    A function rather than ``None`` so a refiner has one code path instead of a
    guard at every checkpoint, and a named module-level one rather than a
    lambda so the protocol, the implementations, and a test can all refer to
    the same object.
    """

    return False
