# Visual check

Capture size: 150×45 cells. Each after-screen PNG came from a pilot with fake services. The pilot used synthetic values only. It did not access audio or a model.

Approved board PNGs:

- Setup: `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/Setup.png`
- Doctor: `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/Doctor.png`

## Setup

| Board element | Result | Comparison |
| --- | --- | --- |
| Steps and detail panels | Matches | The bordered step list is left of the bordered detail panel. |
| Selected step | Matches | The selected Hotkey step uses a bold accent `▶`. Completed steps use `✓`. |
| Capture target | Differs as allowed | The target is a text row. The board uses a dashed key callout. The task allows the text row. |
| Hotkey mode | Matches | Hybrid, hold, and toggle are visible. The current mode is bold accent text. |
| Threshold, bindings, and device | Matches | The detail panel shows each value. |
| Test status | Matches | The status is at the bottom of the detail panel. |
| Key hints | Differs | The existing `e edit` and `Q quick` actions remain visible. Board keycap fills are omitted under task 107. |
| Canvas and panel fills | Overridden | Task 107 prohibits painted backgrounds. The screen and panels do not set a background fill. The no-background pilot test passes. |

## Doctor

| Board element | Result | Comparison |
| --- | --- | --- |
| Check groups | Matches | The two bordered groups sit side by side. |
| Check rows | Matches | Rows use `glyph label · detail`. The `✓`, `!`, and `✗` glyphs use green, warning, and error colors. Each state also has its glyph. |
| Selected issue | Matches | The issue border uses its state color. A bold state-colored title names the issue. One line holds the detail and fix. |
| Repeated detail | Matches after fixture correction | The before capture's fixture repeated `no X display` in both fields. The after fixture uses label `overlay` and detail `No X display.`. The displayed row contains the detail once. |
| Recent warnings | Matches | The panel shows dim time, colored `WARN` or `ERROR`, and the event. It omits the logger name. |
| Sidebar summary and badge | Differs | The sidebar shows detailed counts and check time; its badge is `2W 0F`, rather than the board's `●1`. Task 112 identified the badge as outside its required gaps. This task leaves it unchanged. |
| Key hints | Differs | The existing actions remain. Board keycap fills are omitted under task 107. |
| Canvas and panel fills | Overridden | Task 107 prohibits painted backgrounds. The no-background pilot test passes. The screen's transparent canvas can display the terminal's default background in the PNG. |
