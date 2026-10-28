# SPDX-License-Identifier: GPL-3.0-or-later
"""Session storage package.

- ``models.py`` defines session summaries and loaded session data.
- ``reader.py`` parses session files and derives transcript and audio metrics.
- ``store.py`` exposes safe session operations and an in-memory title and
  transcript search.
- ``exporter.py`` renders transcripts for session and file exports.
- ``persistence.py`` writes private session files atomically.
- ``errors.py`` defines session storage errors.
"""
