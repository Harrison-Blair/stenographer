# SPDX-License-Identifier: GPL-3.0-or-later
"""Interactive hub package.

- __init__.py: Mark the hub package.
- app.py: Run the shell: screens, navigation, sidebar, help, quit, and shell contracts.
- checks_tab.py: Run the system checks; fix, test, and open the setup dialogs.
- choice_dialog.py: List the allowed values of a choice or device setting.
- doctor_panel.py: Render the check list grouped input, engine, and other.
- doctor_view.py: Build doctor checks, model status, and safe warning summaries.
- config_dialog.py: Prompt for config edits, searches, and unsaved changes.
- config_view.py: Validate the config draft and its saves; name, help and control of each key.
- defaults_dialog.py: Confirm before writing the default configuration.
- device_dialog.py: Choose the input device of the next recordings of this run.
- dialogs.py: Confirm actions that stop work during quit.
- export_dialog.py: Choose the export format and folder of a saved session.
- handler.py: Prepare the hub and run its Textual app.
- hub_screen.py: Compose the sidebar, body, and footer shared by each screen.
- files_entry.py: Describe one directory or audio file in the browser.
- files_view.py: Render the file browser, options, queue, and transcript preview.
- library_entry.py: Describe one Library row: a session, a file job, or both.
- library_screen.py: List, search, and act on sessions and file jobs; host Files.
- models_dialog.py: Show each model as present or missing and download one.
- quick_setup_dialog.py: Test and edit input access, microphone, and hotkey.
- record_screen.py: Record, stop and save, watch meters and transcript, rename speakers.
- rename_dialog.py: Rename one speaker of a live or saved session.
- services.py: Own recording, playback, and shared session services.
- session_jobs.py: Reprocess saved transcripts with current models and settings.
- speaker_select.py: Choose a speaker in the rename dialog.
- speaker_select_overlay.py: Mark the highlighted speaker choice without a fill.
- selection.py: Render selected rows with an accent marker and no fill.
- settings_screen.py: Edit the configuration by tab and host the Checks tab.
- setup_test.py: Run the setup workflow probes behind the Checks test key.
- vocabulary_dialog.py: Add, edit and delete the refine vocabulary terms.
- widgets/: Shared widgets: buttons, lists, cards, gauges, hints, and dialogs.
"""
