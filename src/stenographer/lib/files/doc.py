# SPDX-License-Identifier: GPL-3.0-or-later
"""File job data and queue orchestration.

- ``engine.py`` owns the serial background job queue and transcription stages, and saves
  each result as a new file session or as a revision of the session that holds the source.
- ``job.py`` defines synchronized state and progress for one job.
- ``media.py`` probes and decodes soundfile and ffmpeg inputs.
- ``models.py`` defines job options and progress snapshots.
"""
