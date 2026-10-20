# Config visual check

I compared the after capture with the approved board at
`/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/Config.dc.html`
and its rendered PNG at
`/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/Config.png`.
The board sets layout and content. Task 107's no-background rule overrides its
fills.

| Board element | Result | Comparison |
| --- | --- | --- |
| C-1 — Sidebar status | Matches; sample count differs. | The sidebar card shows `config.toml` and a numeric unsaved-change count. The after capture has `0 unsaved changes`; the board sample has `2 unsaved`. The pilot test also checks counts of two and one after draft edits. |
| C-2 — Group selector | Differs by the actual-config rule. | A bordered selector sits to the left of the bordered settings panel. The selected `asr` row uses bold accent text and `▶`, with no fill. The current config has no `live` group, so the selector keeps `delivery` and omits `live`, as the brief requires. |
| C-3 — ASR settings | Overridden by decision 15. | The screen shows one shared ASR settings column. The board's two profile columns are out of date. Existing defaults and help remain visible. |
| C-4 — Recent-line context | Overridden by decision 12. | No context setting appears. The user chose context off, and the benchmark decision keeps it off. |
| C-5 — Hotwords and benchmark note | Matches. | Hotwords have a separate value area below a divider. The beam-size note cites `docs/transcription-experiments.md`, section “CPU model and context screen,” with the beam 1 and beam 5 results. |
| C-6 — Key hints | Matches. | Edit, save, undo, reset, and search remain. The existing group and setting navigation hints also remain. |
| C-7 — Canvas and normal text | Overridden by task 107. | The board's canvas fill is not painted. Normal text uses the terminal foreground; the selected group uses bold accent text without a fill. `test_hub_sections_dialogs_and_live_app_do_not_paint_backgrounds` passes. |

The capture renderer displays its own dark viewer canvas. The no-background pilot
test inspects Textual's rendered cell styles and confirms that the Config
screen paints no background.
