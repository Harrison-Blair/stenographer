# SPDX-License-Identifier: GPL-3.0-or-later
"""Errors raised by session storage operations."""


class SessionNotFoundError(FileNotFoundError):
    """The requested session does not exist under the sessions root."""


class StaleRevisionError(RuntimeError):
    """The current revision changed after the caller read the session."""


class SessionWriteCancelledError(RuntimeError):
    """A session write stopped at a cancel request and removed what it made."""


class SessionSourceError(FileNotFoundError):
    """A file session has no valid source audio in its folder."""
