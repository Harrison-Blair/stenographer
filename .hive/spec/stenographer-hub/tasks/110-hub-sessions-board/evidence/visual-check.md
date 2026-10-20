# Sessions visual check

Board: `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/Sessions.dc.html`

Board PNG: `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/Sessions.png`

Screen captures: `before-sessions.{svg,txt,png}` and
`after-sessions.{svg,txt,png}`. Both use a 150 by 45 Textual pilot with fake
services. The captures contain no transcript text. The after screen uses an
empty transcript; the pilot test checks transcript rendering separately.

| Board element | Result | Difference or override |
| --- | --- | --- |
| Six-section sidebar | Matches. | The selected row uses bold accent text and `▶`. The board's selected-row fill is overridden by task 107's no-background rule. |
| Storage card | Matches. | It sits below the sidebar and shows the session count and audio size. The fixture shows 3.9 MB; the board example shows 4.1 MB. |
| Saved list panel | Matches. | It has a separate border, a `saved` title, and session date, duration, and speaker count. |
| Selected session row | Differs by rule. | The board uses a row fill and `▸`. Task 107 requires a bold accent `▶` marker with no fill. |
| Session detail panel and title | Matches. | The selected session ID is the border title. The detail shows label status. |
| Speaker talk-time chips | Matches. | The labels and times are present in bold accent text. Chip fills are overridden by task 107's no-background rule. |
| Microphone and system activity | Matches. | Both sources have separate waveform rows. The captured meter values are synthetic. |
| Transcript separator and lines | Differs in the capture. | The capture has no transcript lines to keep transcript text out of evidence. The pilot test checks timestamps, speaker labels, and transcript lines. Speaker-chip fills are overridden by task 107. |
| Key hints | Matches. | Playback, re-diarization, re-transcription, rename, export, and delete remain listed. |
| Canvas and normal text | Overridden. | The board's canvas fill is overridden by task 107. Normal text uses the terminal default foreground. |

## Gap-to-test map

| Gap | Fix | Test |
| --- | --- | --- |
| Widget CSS bug | Move Sessions styles to `DEFAULT_CSS`; use supported spacing. | `test_sessions_panels_render_borders_and_board_proportions` |
| S-1 | Move count and audio size to the shared sidebar card. | `test_sessions_list_and_detail_show_storage_activity_and_transcript`; `test_active_recording_is_not_listed_as_a_saved_session` |
| S-2 | Keep the saved list in its own proportional panel and apply the selected marker style. | `test_sessions_panels_render_borders_and_board_proportions`; `test_sessions_list_and_detail_show_storage_activity_and_transcript` |
| S-3 | Show label status, speaker talk time, source activity, and styled transcript labels in the detail panel. | `test_sessions_list_and_detail_show_storage_activity_and_transcript`; `test_session_rename_export_and_delete_use_confirmed_session` |
| S-4 | Apply borders to the list and detail panels. | `test_sessions_panels_render_borders_and_board_proportions` |
