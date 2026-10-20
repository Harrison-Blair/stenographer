# SPDX-License-Identifier: GPL-3.0-or-later
"""Interactive hub package.

- __init__.py: Mark the hub package.
- app.py: Render sections and coordinate hub-level user actions.
- doctor_view.py: Build grouped doctor checks and safe warning summaries.
- config_dialog.py: Prompt for config edits, searches, and unsaved changes.
- config_view.py: Render and validate the config draft and its saves.
- dialogs.py: Confirm actions that stop work during quit.
- handler.py: Prepare the hub and run its Textual app.
- live_view.py: Render live recording status and mixed or split transcripts.
- services.py: Own recording, playback, and shared session services.
- session_jobs.py: Reprocess saved transcripts with current models and settings.
- sessions_view.py: Render saved-session storage, list, detail, and transcript.
- setup_state.py: Track wizard navigation and completion state.
- setup_wizard.py: Render setup steps and reuse setup workflow probes.
"""
