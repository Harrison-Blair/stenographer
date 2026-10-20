# Visual check

I rendered Live idle, mixed, and split states at 150x45 cells in a Textual
pilot with fake services. The current captures are
`after-live-{idle,mixed,split}.{svg,txt,png}`. The mixed and split captures use
synthetic fixture lines. No audio device, model, `live`, or `run` was used.

I compared the mixed capture with the approved StenoB board and the split
capture with the approved LiveSplit board:

- StenoB: `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/StenoB.png`
- LiveSplit: `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/LiveSplit.png`

## Board comparison

| Board element | Result | Comparison |
| --- | --- | --- |
| StenoB L-1 — sidebar and status card | Matches | Six sections appear above the bordered card. The mixed fixture shows `medium.en int8`, queue, failed count, and CPU. In the idle capture, the longer configured model name wraps `int8` onto the next line; the board's sample name `medium.en` fits on one line. |
| StenoB L-2 — selected section | Matches | Live uses a bold accent `▶` marker and has no selected-row fill. |
| StenoB L-3 — REC panel | Matches | The panel shows one inline `● REC` label and the large elapsed-time digits. The border title is empty. |
| StenoB L-4 — MIC panel | Matches | The source state, device, waveform meter, and dBFS appear together. The fake device is `Default input`; the board sample is `QuadCast`. |
| StenoB L-5 — SYSTEM panel | Matches | The source state, shortened device, waveform meter, and dBFS appear together. The fake device is shortened to `Default output…`; the board sample is `Arena 7`. |
| StenoB L-6 — mixed transcript | Matches | The bordered panel shows time, speaker label, and text. Speaker labels are bold accent text with no fill. Fixture timestamps and transcript lines differ from the board's sample content. |
| StenoB L-7 — key hints | Matches | Hints include `v view: mixed / split`; `mixed` is bold in mixed view and `split` is bold in split view. Keys use bold accent text, and descriptions use the default foreground. |
| StenoB L-8 — canvas fill | Overridden | Task 107's no-background rule overrides the board's canvas fill. The no-background pilot test passes; the app does not paint a background. |
| LiveSplit LS-1 — transcript columns | Matches | Split view has a time column and captioned `MIC · what you said` and `SYSTEM · everyone else` columns. |
| LiveSplit LS-2 — empty source cells | Matches | An empty source cell shows `·`. |
| LiveSplit LS-3 — speaker labels | Matches | Speaker labels use bold accent text without a fill, as in mixed view. |
| LiveSplit LS-4 — shared panels and hints | Matches | REC, MIC, and SYSTEM stay above the split transcript. The view hint names both modes and bolds `split`. |
| Shared F-1, S-1, C-1, D-1 — section card | Matches | The shared bordered card sits below navigation on each section. Live sets its engine, model, compute type, queue, failed count, and CPU. The pilot tests the section-owned card API with Live and Files content. |

The SVG-to-PNG renderer joins some adjacent styled text runs visually (for
example, `v view` can look like `vview`). The SVG compositor text confirms the
spaces. The selected view's bold style is also asserted in the pilot for both
states. The PNG renderer can make border corners uneven; the Textual widget
borders and pilot structure assertions confirm the borders.

## Gap, fix, and test map

| Gap | Fix | Pilot assertion |
| --- | --- | --- |
| L-1 | Show the active model and configured compute type in the Live card. | `test_sidebar_card_is_section_owned_and_live_shows_engine_status` |
| L-2 | Use the bold accent selection marker from task 107. | `test_selected_sidebar_and_file_rows_use_bold_accent_marker` |
| L-3 | Keep only the inline REC label; retain the large elapsed-time `Digits` widget. | `test_live_rec_panel_shows_only_the_inline_rec_label`; `test_live_elapsed_uses_digits_widget` |
| L-4 | Show MIC source, device, meter, and dBFS in one bordered panel. | `test_pilot_live_has_board_panels_and_captioned_split_columns` |
| L-5 | Show SYSTEM source, shortened device, meter, and dBFS in one bordered panel. | `test_system_source_state_and_device_fit_on_one_line` |
| L-6 | Show a bordered mixed transcript with stable colored speaker labels. | `test_live_speaker_colors_are_distinct_stable_and_used_in_rename_choices` |
| L-7 | Show both view names and bold the active view in the key hint. | `test_live_view_hint_names_both_modes_and_bolds_the_current_mode` |
| L-8 | Keep app backgrounds unpainted. | `test_hub_sections_dialogs_and_live_app_do_not_paint_backgrounds` |
| LS-1 | Show time and captioned MIC/SYSTEM columns. | `test_pilot_live_has_board_panels_and_captioned_split_columns`; `test_pilot_live_mixed_and_split_views_keep_time_order` |
| LS-2 | Show `·` for an empty source cell. | `test_pilot_live_has_board_panels_and_captioned_split_columns` |
| LS-3 | Reuse speaker label styles in split view. | `test_live_speaker_colors_are_distinct_stable_and_used_in_rename_choices` |
| LS-4 | Keep the shared panels and stateful view hint above the split transcript. | `test_pilot_live_has_board_panels_and_captioned_split_columns`; `test_live_view_hint_names_both_modes_and_bolds_the_current_mode` |
| F-1, S-1, C-1, D-1 | Provide the shared section-owned card API and Live card content. | `test_sidebar_card_is_section_owned_and_live_shows_engine_status` |
