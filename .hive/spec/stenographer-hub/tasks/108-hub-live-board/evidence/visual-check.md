# Visual check

The pilot renders use fake services at 150 by 45 cells. They do not use a
microphone, system capture, a model, `live`, or `run`. The before and after SVG
and text files are in this folder. The PNG files show those same captures.
The approved board images remain outside the repository:

- StenoB: `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/StenoB.png`
- LiveSplit: `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/LiveSplit.png`

## Board comparison

| Board element | Result | Comparison |
| --- | --- | --- |
| StenoB L-1 — sidebar and status card | Matches | The six-section list sits above its own bordered card. Live sets the model, queue, failed count, and CPU. The card API accepts content for each section; the Files, Sessions, Config, and Doctor tasks will set their content. |
| StenoB L-2 — selected section | Matches | Live uses bold accent text and `▶`. The board's selected-row fill is overridden by the no-background rule. |
| StenoB L-3 — REC panel | Differs | The panel shows a bold elapsed time on its own line. Textual uses one terminal font size, so the time cannot use the board's larger font. |
| StenoB L-4 — MIC panel | Matches | The panel shows the source, state, device, waveform meter, and dBFS level. |
| StenoB L-5 — SYSTEM panel | Differs | The panel shows the source, state, device, waveform meter, and dBFS level. The longer default device name wraps to a second line at this terminal width. |
| StenoB L-6 — mixed transcript | Matches | The bordered panel shows time, bold accent speaker labels, and text. Chip fills are overridden by the no-background rule. |
| StenoB L-7 — key hints | Matches | Live shows pause, source toggles, view, rename, stop/save, and `1-6 sections`. Keycap fills are overridden by the no-background rule. |
| StenoB L-8 — canvas and normal text | Overridden | The screen and widgets leave backgrounds transparent and use the terminal foreground. Task 107's no-background rule overrides the board's dark canvas fill. |
| LiveSplit LS-1 — transcript columns | Matches | A time column precedes the captioned MIC and SYSTEM columns. Rows stay in time order. |
| LiveSplit LS-2 — empty source cells | Matches | An empty MIC or SYSTEM cell shows `·` on its time row. |
| LiveSplit LS-3 — speaker labels | Matches | Labels use bold accent text with no fill. The board's chip fills are overridden by the no-background rule. |
| LiveSplit LS-4 — shared header and hints | Matches | REC, MIC, and SYSTEM panels remain above the transcript. The key-hint row includes `1-6 sections`. |
| Shared F-1, S-1, C-1, D-1 — section card | Matches | The bordered card is present below the section list on every screen. This task provides the per-section setter and Live content. Other screen tasks will supply their card content. |

## Gap, fix, and test map

| Gap | Fix | Regression test |
| --- | --- | --- |
| L-1 | Add the shared sidebar card and Live engine/model/queue/failure/CPU content. | `test_sidebar_card_is_section_owned_and_live_shows_engine_status` |
| L-2 | Keep the task 107 selected-row marker and bold accent style. | `test_selected_sidebar_and_file_rows_use_bold_accent_marker` |
| L-3 | Add the bordered REC panel and separate elapsed-time line. | `test_pilot_live_has_board_panels_and_captioned_split_columns` |
| L-4 | Add the bordered MIC panel with device, waveform, and dBFS. | `test_pilot_live_has_board_panels_and_captioned_split_columns` |
| L-5 | Add the bordered SYSTEM panel with device, waveform, and dBFS. | `test_pilot_live_has_board_panels_and_captioned_split_columns` |
| L-6 | Add the bordered mixed transcript and accent speaker labels. | `test_pilot_live_has_board_panels_and_captioned_split_columns`; `test_pilot_live_mixed_and_split_views_keep_time_order` |
| L-7 | Add `1-6 sections` to Live hints. | `test_pilot_live_has_board_panels_and_captioned_split_columns` |
| L-8 | Keep all Live backgrounds transparent and text in the terminal foreground. | `test_hub_sections_dialogs_and_live_app_do_not_paint_backgrounds` |
| LS-1 | Render the split view as time, MIC, and SYSTEM columns with captions. | `test_pilot_live_has_board_panels_and_captioned_split_columns`; `test_pilot_live_mixed_and_split_views_keep_time_order` |
| LS-2 | Render `·` for each empty source cell. | `test_pilot_live_has_board_panels_and_captioned_split_columns` |
| LS-3 | Style labels as bold accent text without a fill. | `test_pilot_live_has_board_panels_and_captioned_split_columns`; `test_hub_sections_dialogs_and_live_app_do_not_paint_backgrounds` |
| LS-4 | Keep the three Live panels and section key hint above the split view. | `test_pilot_live_has_board_panels_and_captioned_split_columns` |
| F-1, S-1, C-1, D-1 | Add one shared card widget and a setter keyed by section; Live sets its card. | `test_sidebar_card_is_section_owned_and_live_shows_engine_status` |
