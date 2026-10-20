# Sessions visual check

Board: `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/Sessions.dc.html`

Board PNG: `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/Sessions.png`

Screen captures: `before-sessions.{svg,txt,png}` and
`after-sessions.{svg,txt,png}`. Both use a 150-by-45 Textual pilot with fake
services. The after capture uses synthetic session and transcript fixtures.

| Board element | Result | Difference or override |
| --- | --- | --- |
| Six-section sidebar | Matches. | The selected row uses bold accent text and `▶`. The board's selected-row fill is overridden by task 107's no-background rule. |
| Storage card | Differs in sample value. | It sits below the sidebar and shows the session count and audio size. The fixture shows 3 sessions and 1.1 KB audio; the board example shows 3 sessions and 4.1 MB audio. |
| Saved list panel | Matches. | It has its own border, a readable bold `saved` title, and session date, duration, and speaker count. |
| Selected session row | Differs by rule. | The board uses a row fill and `▸`. Task 107 requires a bold accent `▶` marker with no fill. |
| Session detail title and label status | Differs in metadata. | The bold session ID and label status share the first content row, with the status right-aligned. The fixture status is `live`; the board example says `re-labelled at stop`. |
| Speaker talk-time labels | Differs in fixture data. | The fixture shows `You` and `Speaker 1`; the board example has three speakers. The labels use bold accent text. Chip fills are overridden by task 107's no-background rule. |
| Microphone and system activity | Differs in meter shape. | Both source rows appear. The fixture uses constant synthetic audio, so the meters are flat blocks; the board shows changing levels. |
| Transcript rule and lines | Matches. | The rule fills the available width on first render. Under it, the capture shows timestamps, coloured bold speaker labels, and synthetic fixture text. The timestamps and text differ from the board example. Speaker-chip fills are overridden by task 107. |
| Key hints | Matches. | Playback, re-diarization, re-transcription, rename, export, and delete remain listed. |
| Canvas and normal text | Overridden. | Task 107's no-background rule overrides the board's canvas fill. Normal text uses the terminal default foreground. |

## Gap-to-test map

| Gap | Fix | Test |
| --- | --- | --- |
| Widget CSS bug | Keep Sessions layout rules in `DEFAULT_CSS`, with a laid-out `Rule` widget. | `test_sessions_panels_render_borders_and_board_proportions`; `test_sessions_transcript_rule_fills_detail_width_on_first_layout` |
| S-1 | Show count and audio size in the shared sidebar card. | `test_sessions_list_and_detail_show_storage_activity_and_transcript`; `test_active_recording_is_not_listed_as_a_saved_session` |
| S-2 | Keep the saved list in its own panel and use the selected marker style. | `test_sessions_panels_render_borders_and_board_proportions`; `test_sessions_list_and_detail_show_storage_activity_and_transcript` |
| S-3 | Show session title, right-aligned label status, talk time, source activity, and transcript speaker labels. | `test_session_label_status_is_right_aligned_on_the_title_row`; `test_sessions_list_and_detail_show_storage_activity_and_transcript`; `test_sessions_transcript_rows_render_after_rule_with_synthetic_text` |
| S-4 | Give the list and detail panels separate borders with readable titles. | `test_sessions_panels_render_borders_and_board_proportions`; `test_sessions_border_titles_use_default_foreground_and_bold` |
