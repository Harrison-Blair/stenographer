# Files visual check

I compared `after-files.png` with the approved board PNG:

`/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/Files.png`

The SVG and text captures came from a 150 by 45 pilot with fake services. The
before and after captures use the same synthetic file list and queue state.
The text capture confirms spaces where the SVG-to-PNG renderer can visually
join adjacent styled runs.

## Board comparison

| Board element | Result | Comparison |
| --- | --- | --- |
| F-1 — sidebar and engine card | Differs by decision | The sidebar card has engine, model, compute type, and CPU. The board's `accurate` profile label is omitted because the tool has one shared ASR configuration and no per-use profiles (goal decision 12). |
| F-2 — main panels | Matches | The browser is on the left. Options and queue are stacked on the right. The preview is below them. The pilot verifies borders, equal columns, equal right-panel heights, and the 3:2 row heights. |
| F-3 — selected file | Overridden | The selected file uses bold accent text and a `▶` marker without a fill, as task 107 requires. |
| F-4 — options | Matches | Diarization, speaker count, an on/off refine toggle, all four formats, and the output folder appear in the options panel. The active format uses bold accent text. |
| F-5 — queue progress | Matches | Each job shows a progress bar, percentage, ETA, and stage checklist. Completed stages use `✓`; the current stage uses `…`; upcoming stages have no marker. |
| F-6 — preview | Differs slightly | The border title uses the result file stem. Preview lines show `HH:MM:SS`, a bold accent speaker label with no fill, and text. The existing saved-result line remains below the preview. |
| F-7 — key hints | Matches | The hints include `e open result` and `1-6 sections`. Key fills are omitted under task 107. |
| F-8 — canvas and normal text | Overridden | Task 107's no-background rule removes the board's canvas fill. Normal text uses the terminal foreground. The no-background pilot passes. |

## Gap, fix, and test map

| Gap | Fix | Test |
| --- | --- | --- |
| F-1 | Populate the Files sidebar card with engine, model, compute type, and CPU. | `test_files_panels_have_board_layout_and_files_sidebar_card` |
| F-2 | Move the Files layout rules to `FilesPanel.DEFAULT_CSS`; use supported margins for the panel gaps. | `test_files_panels_have_board_layout_and_files_sidebar_card` |
| F-3 | Keep the selected file's bold accent `▶` style with no fill. | `test_selected_sidebar_and_file_rows_use_bold_accent_marker` |
| F-4 | Render diarization and speaker count together, show refine as on/off, and list the format choices. | `test_files_options_queue_preview_and_key_hints_match_board`; `test_pilot_file_options_can_be_changed` |
| F-5 | Add a proportional progress bar and completed/current/upcoming stage checklist. | `test_files_options_queue_preview_and_key_hints_match_board`; `test_pilot_queue_progress_preview_cancel_and_open_result_folder` |
| F-6 | Put the result stem in the border title and render timestamped speaker labels in bold accent text without a fill. | `test_files_options_queue_preview_and_key_hints_match_board` |
| F-7 | Label `e` as `open result` and include the section keys. | `test_files_options_queue_preview_and_key_hints_match_board` |
| F-8 | Leave backgrounds transparent and normal text at the terminal foreground. | `test_hub_sections_dialogs_and_live_app_do_not_paint_backgrounds` |
