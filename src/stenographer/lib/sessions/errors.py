# SPDX-License-Identifier: GPL-3.0-or-later
"""Errors raised by session storage operations."""


class SessionNotFoundError(FileNotFoundError):
    """The requested session does not exist under the sessions root."""
