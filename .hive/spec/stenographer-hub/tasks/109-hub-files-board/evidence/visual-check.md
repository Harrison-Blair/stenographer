# Files visual check

I compared the repaired Files screen with the approved board PNG at
`/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/Files.png`.
The board source is
`/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/Files.dc.html`.
The screen capture used a 150 by 45 pilot with fake services, fixture file
metadata, a synthetic queue job, and synthetic preview lines. It did not
capture audio or use a model. The before capture is the task-base screen. The
after PNG and SVG were re-captured after the V4 repairs; the text render is
beside them.

## Board comparison

| Board element | Result | Comparison |
| --- | --- | --- |
| F-1 — sidebar and engine card | Differs by decision | The card shows the engine, model, compute type, and CPU. It omits the board's `accurate` profile label because the tool has one shared ASR configuration and no per-use profiles (goal decision 12). |
| F-2 — main panel placement | Differs slightly | The browser is on the left, options and queue are on the right, and preview is below. All four panels have borders and the intended proportions. The screen gives the queue its own bordered panel; the board nests it below the options rows with a divider. |
| F-2 — panel titles | Matches | The four titles use bold terminal-default foreground. The browser title tracks its folder (`~/Recordings`) instead of saying `browser`. The current folder appears in the title, not as a duplicate body row. |
| F-2 — browser key hint | Matches | `/ search · enter queue · space select` is in a fixed footer at the bottom of the browser panel, as on the board. The file list scrolls separately above it. |
| F-2 — file order | Differs | The screen sorts the fixture files alphabetically. The board uses a different sample order with `standup-2026-10-19.m4a` first. |
| F-3 — selected file | Overridden | The selected file uses bold accent text and a `▶` marker without a fill, as task 107 requires. |
| F-4 — options | Matches | The diarize state, speaker count, refine toggle, formats, and output folder are present. The visible chosen values (`[x] diarize`, `auto`, `[ ] cleanup pass`, and `md`) use the accent color. Refine uses `[ ] cleanup pass` / `[x] cleanup pass`, which maps directly to the boolean `refine` option. |
| F-5 — queue progress | Matches | The job shows a progress bar, `58%`, ETA `1:40`, and the stage checklist. Completed stages use `✓`, the current stage uses `…`, and upcoming stages have no marker. |
| F-6 — preview | Differs slightly | The title names the result stem. Three synthetic fixture rows show timestamps, bold accent speaker labels, and text without fills. The screen also shows the existing `saved:` result line; the board uses different sample transcript lines and has no saved line. Speaker-chip fills are overridden by task 107. |
| F-7 — key hints | Matches | The hints include `e open result` and `1-6 sections`. Key fills are omitted under task 107. |
| F-8 — canvas and normal text | Overridden | Task 107's no-background rule removes the board's canvas fill. Panel, selected-row, and speaker-label styles do not paint a fill. The no-background pilot passes; the screenshot uses the terminal's default background. |

## Gap, fix, and test map

| Gap | Fix | Test |
| --- | --- | --- |
| F-1 | Keep the Files sidebar card populated with engine, model, compute type, and CPU. | `test_files_panels_have_board_layout_and_files_sidebar_card` |
| F-2 | Apply Files title styles in App CSS; set the browser title from the current folder; keep the panel layout and pin the browser hint below the file list. | `test_files_panel_titles_use_terminal_foreground_and_bold`; `test_files_browser_title_tracks_current_directory`; `test_files_browser_hint_is_pinned_to_panel_bottom`; `test_files_panels_have_board_layout_and_files_sidebar_card` |
| F-3 | Keep the selected file's bold accent `▶` style with no fill. | `test_selected_sidebar_and_file_rows_use_bold_accent_marker` |
| F-4 | Show refine as `[ ]/[x] cleanup pass` and color the visible choice values in accent. | `test_files_chosen_option_values_use_accent_color`; `test_pilot_file_options_can_be_changed` |
| F-5 | Show percentage, progress bar, ETA, and completed/current/upcoming stages. | `test_files_options_queue_preview_and_key_hints_match_board`; `test_pilot_queue_progress_preview_cancel_and_open_result_folder` |
| F-6 | Put the result stem in the border title and show timestamped, bold accent speaker labels without fills. | `test_files_options_queue_preview_and_key_hints_match_board` |
| F-7 | Label `e` as `open result` and include the section keys. | `test_files_options_queue_preview_and_key_hints_match_board` |
| F-8 | Keep backgrounds transparent and normal text at the terminal foreground. | `test_hub_sections_dialogs_and_live_app_do_not_paint_backgrounds` |
