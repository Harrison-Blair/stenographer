# SPDX-License-Identifier: GPL-3.0-or-later
"""Optional local cleanup of a finished transcript through a local Ollama model.

The stage is off by default and always fails open: any timeout, transport
error, malformed reply, or suspicious output delivers the locally formatted
transcript unchanged. Nothing in this package logs, raises, or persists
transcript text; only counts, durations, and outcome names leave it.
"""
