# Config visual check

I compared the repaired Config screen with the approved board at
`/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/Config.dc.html`
and its rendered PNG at
`/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/Config.png`.
The board sets layout and content. Task 107's no-background rule overrides its
fills. The 150×45 after capture uses fake services, `beam_size = 5`, 40 synthetic
hotwords, and one draft edit to `idle_unload_seconds = 4`. It selects the ASR
group and `beam_size`. The screen shows changed-value dots, one unsaved change,
a width-limited hotword preview, and the beam benchmark note.

`after-config.svg` is the direct `app.save_screenshot()` output. The PNG render
uses a temporary copy with `xml:space="preserve"`. The raw SVG omits this
attribute, so `rsvg-convert` otherwise drops leading terminal spaces and shifts
the value column. `after-config.txt` records the unmodified compositor output.
The regression test checks the selected marker and the name/value cell columns.

| Board element | Result | Comparison |
| --- | --- | --- |
| C-1 — Sidebar status | Matches. | The card shows `config.toml` and `1 unsaved change` in the warning color. The board sample has two changes; the screen shows the actual draft count. Tests check zero, one, and two changes. |
| C-2 — Group selector | Differs by the actual-config rule. | A bordered selector sits left of the settings panel. The selected `asr` row uses bold accent `▶` text and no fill. The current config has no `live` settings, so the selector omits `live` and keeps `delivery`, as requirement 4 directs. |
| Settings panel title | Matches after repair. | The `asr` title uses the default foreground and bold style. The board's `asr · profiles` wording is outdated; decision 15 calls for one shared ASR settings column. |
| C-3 — Settings table | Matches the manager's scope decision; sample values differ. | The settings panel has one name/value row per key and one value column. The selected `beam_size` row uses the same two-cell marker width as the unselected indent; the pilot cell output keeps the value column aligned. A warn-coloured `●` follows values that differ from defaults. The board's two profile columns are overridden by decision 15. |
| C-4 — Recent-line context | Omitted by the user's choice. | No context key appears. The current config has no context setting, as the brief directs. |
| C-5 — Hotwords value area | Matches. | Hotwords have a separate value area with no fill. The capture shows 16 of 40 synthetic terms and `… 40 words`; tests confirm empty values show `none`, short lists show in full without an ellipsis, and long lists truncate to the panel width. The selected `beam_size` help cites `docs/transcription-experiments.md`, section “CPU model and context screen.” |
| C-6 — Key hints | Matches. | Edit, save, undo, reset, and search remain. Group and setting navigation hints also remain. |
| C-7 — Canvas and selected rows | Overridden by task 107. | The screen paints no background. Normal text uses the terminal foreground. A selected row uses bold accent text and `▶`, with no fill. The no-background pilot test passes. |

The PNG renderer shows a dark viewer canvas. The no-background test inspects the
Textual cell styles and confirms that the Config screen paints no background.
