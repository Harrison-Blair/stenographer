# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations


class ProtocolError(ValueError):
    """A malformed helper message, described without reproducing its payload."""
