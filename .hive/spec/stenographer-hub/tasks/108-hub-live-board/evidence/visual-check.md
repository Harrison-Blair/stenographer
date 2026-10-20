# Visual check

The Live idle, mixed, and split screens use fake services in a 150x45 Textual
pilot. The current captures are `after-live-{idle,mixed,split}.{svg,txt,png}`.
The before captures remain `before-live-{idle,mixed,split}.{svg,txt,png}`.
The approved board images remain outside this repository:

- StenoB: `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/StenoB.png`
- LiveSplit: `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/LiveSplit.png`

No microphone, system capture, model, `live`, or `run` was used.

## Board comparison

| Board element | Result | Comparison |
| --- | --- | --- |
| StenoB L-1 — sidebar and status card | Matches | Six sections appear above the bordered card. Live sets the engine, model, queue, failed count, and CPU. |
| StenoB L-2 — selected section | Matches | The selected row uses bold accent text and `▶` with no fill. |
| StenoB L-3 — REC panel | Matches | Elapsed time uses Textual `Digits` and displays in a large 3-row form. |
| StenoB L-4 — MIC panel | Matches | The source, state, device, waveform meter, and dBFS appear in one panel. |
| StenoB L-5 — SYSTEM panel | Matches | The source, state, shortened device, waveform meter, and dBFS appear in one panel. The test device is `Default output…`; the board's device is shorter. |
| StenoB L-6 — mixed transcript | Matches | The bordered transcript shows times, text, and bold labels. You is cyan; system speakers use stable distinct palette colors. Labels have no fill. |
| StenoB L-7 — key hints | Matches | Keys use bold accent text. Descriptions use the terminal default foreground. There are no key fills. |
| StenoB L-8 — canvas and normal text | Overridden | Task 107's no-background rule overrides the board canvas fill. The no-background test passes. |
| LiveSplit LS-1 — transcript columns | Matches | Split view shows time, `MIC · what you said`, and `SYSTEM · everyone else` in time order. |
| LiveSplit LS-2 — empty source cells | Matches | Each empty source cell shows `·`. |
| LiveSplit LS-3 — speaker labels | Matches | Labels keep their speaker colors in split view and have no fill. |
| LiveSplit LS-4 — shared header and hints | Matches | REC, MIC, and SYSTEM stay above the split transcript. Key hints use accent keys and default-foreground descriptions. |
| Shared F-1, S-1, C-1, D-1 — section card | Matches | Each section has the shared bordered sidebar card. This task provides its API and Live content. |

The SVG-to-PNG conversion can make adjacent styled text runs look joined and
can make border corners look uneven. These known rsvg spacing and corner
artifacts are visible in the PNGs; the pilot text and compositor confirm the
spaces and borders. They are not screen defects.

## Gap, fix, and test map

| Gap | Fix | Pilot assertion |
| --- | --- | --- |
| L-1 | Shared sidebar card with Live status content. | `test_sidebar_card_is_section_owned_and_live_shows_engine_status` |
| L-2 | Bold accent selection marker from task 107. | `test_selected_sidebar_and_file_rows_use_bold_accent_marker` |
| L-3 | Large elapsed-time `Digits` widget in REC. | `test_live_elapsed_uses_digits_widget`; `test_pilot_live_has_board_panels_and_captioned_split_columns` |
| L-4 | Bordered MIC panel with device, waveform, and dBFS. | `test_pilot_live_has_board_panels_and_captioned_split_columns` |
| L-5 | Bordered SYSTEM panel with one-line truncated device. | `test_system_source_state_and_device_fit_on_one_line` |
| L-6 | Bordered mixed transcript with stable distinct speaker colors. | `test_live_speaker_colors_are_distinct_stable_and_used_in_rename_choices` |
| L-7 | Bold accent keys and default-foreground descriptions. | `test_live_key_hints_style_keys_and_descriptions_without_fills` |
| L-8 | Keep backgrounds unpainted. | `test_hub_sections_dialogs_and_live_app_do_not_paint_backgrounds` |
| LS-1 | Time column and captioned MIC/SYSTEM columns. | `test_pilot_live_has_board_panels_and_captioned_split_columns`; `test_pilot_live_mixed_and_split_views_keep_time_order` |
| LS-2 | Show `·` for an empty source. | `test_pilot_live_has_board_panels_and_captioned_split_columns` |
| LS-3 | Keep per-speaker styles in split view. | `test_live_speaker_colors_are_distinct_stable_and_used_in_rename_choices` |
| LS-4 | Keep shared panels and styled hints above split transcript. | `test_pilot_live_has_board_panels_and_captioned_split_columns`; `test_live_key_hints_style_keys_and_descriptions_without_fills` |
| F-1, S-1, C-1, D-1 | Shared section-owned sidebar card API. | `test_sidebar_card_is_section_owned_and_live_shows_engine_status` |
