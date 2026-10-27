# SPDX-License-Identifier: GPL-3.0-or-later
"""Interactive hub package.

- __init__.py: Mark the hub package.
- app.py: Run the shell: screens, navigation, sidebar, help, quit, and shell contracts.
- choice_dialog.py: List the allowed values of a choice or device setting.
- checks_tab.py: Run the system checks and setup actions of the Settings Checks tab.
- doctor_panel.py: Render grouped checks, issue details, and recent warnings.
- doctor_view.py: Build doctor checks and safe warning summaries.
- config_dialog.py: Prompt for config edits, searches, and unsaved changes.
- config_view.py: Validate the config draft and its saves; name, help and control of each key.
- dialogs.py: Confirm actions that stop work during quit.
- handler.py: Prepare the hub and run its Textual app.
- hub_screen.py: Compose the sidebar, body, and footer shared by each screen.
- files_entry.py: Describe one directory or audio file in the browser.
- files_view.py: Render the file browser, options, queue, and transcript preview.
- library_screen.py: Show saved sessions and the Files sub-view.
- live_view.py: Render live recording status and mixed or split transcripts.
- record_screen.py: Start, pause, and watch a recording.
- services.py: Own recording, playback, and shared session services.
- session_jobs.py: Reprocess saved transcripts with current models and settings.
- sessions_view.py: Render saved-session storage, list, detail, and transcript.
- selection.py: Render selected rows with an accent marker and no fill.
- settings_screen.py: Edit the configuration by tab and host the Checks tab.
- setup_test.py: Run the setup workflow probes behind the Checks test key.
- vocabulary_dialog.py: Add, edit and delete the refine vocabulary terms.
- widgets/: Shared widgets: buttons, lists, cards, gauges, hints, and dialogs.
"""
