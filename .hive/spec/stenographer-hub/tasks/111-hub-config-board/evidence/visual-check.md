# Config visual check

I compared the repaired Config screen with the approved board at
`/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/Config.dc.html`
and its rendered PNG at
`/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/Config.png`.
The board sets layout and content. Task 107's no-background rule overrides its
fills. The after capture uses the actual default config and selects
`beam_size`, so the selected-key benchmark details appear at the panel bottom.

| Board element | Result | Comparison |
| --- | --- | --- |
| C-1 — Sidebar status | Matches in content; sample count differs. | The sidebar card shows `config.toml` and the numeric unsaved-change count. The capture has `0 unsaved changes`; the board sample has `2 unsaved`. Tests check counts of two and one after draft edits. |
| C-2 — Group selector | Differs by the actual-config rule. | A bordered selector sits left of the settings panel. The selected `asr` row uses bold accent `▶` text and no fill. The current config has no `live` settings, so the selector omits `live` and keeps `delivery`, as requirement 4 directs. |
| Settings panel title | Matches after repair. | The `asr` title uses the default foreground and bold style. The board's `asr · profiles` wording is outdated; decision 15 calls for one shared ASR settings column. |
| C-3 — Settings table | Matches the manager's scope decision; sample values differ. | The settings panel has one name/value row per key, one value column, a warn-coloured `●` after values that differ from their defaults, and one bottom help item for the selected key. The screen uses the actual default model and values. The board's two profile columns are overridden by decision 15. |
| C-4 — Recent-line context | Omitted by the user's choice. | No context key appears. The current config has no context setting, as the brief directs. |
| C-5 — Hotwords value area | Matches in layout and count; sample value differs. | Hotwords have a separate value area with a preview and `… N words`, with no fill. The actual default is unset, so the capture shows `(unset) … 0 words`; the board uses a sample list and shows `45 words`. The selected `beam_size` help includes the benchmark results and cites `docs/transcription-experiments.md`, section “CPU model and context screen.” |
| C-6 — Key hints | Matches. | Edit, save, undo, reset, and search remain. Group and setting navigation hints also remain. |
| C-7 — Canvas and selected rows | Overridden by task 107. | The screen paints no background. Normal text uses the terminal foreground. A selected row uses bold accent text and `▶`, with no fill. The no-background pilot test passes. |

The PNG renderer shows a dark viewer canvas. The no-background test inspects the
Textual cell styles and confirms that the Config screen paints no background.
