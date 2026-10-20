# SPDX-License-Identifier: GPL-3.0-or-later
"""Interactive hub package.

- __init__.py: Mark the hub package.
- app.py: Render sections and coordinate hub-level user actions.
- doctor_panel.py: Render grouped checks, issue details, and recent warnings.
- doctor_view.py: Build doctor checks and safe warning summaries.
- config_dialog.py: Prompt for config edits, searches, and unsaved changes.
- config_view.py: Render and validate the config draft and its saves.
- dialogs.py: Confirm actions that stop work during quit.
- handler.py: Prepare the hub and run its Textual app.
- files_entry.py: Describe one directory or audio file in the browser.
- files_view.py: Render the file browser, options, queue, and transcript preview.
- live_view.py: Render live recording status and mixed or split transcripts.
- services.py: Own recording, playback, and shared session services.
- session_jobs.py: Reprocess saved transcripts with current models and settings.
- sessions_view.py: Render saved-session storage, list, detail, and transcript.
- selection.py: Render selected rows with an accent marker and no fill.
- setup_panel.py: Render the selected setup step beside the step list.
- setup_state.py: Track wizard navigation and completion state.
- setup_wizard.py: Render setup state and reuse setup workflow probes.
"""
