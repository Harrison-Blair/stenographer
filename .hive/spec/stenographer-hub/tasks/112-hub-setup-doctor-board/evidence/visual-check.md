# Visual check

I rendered Setup and Doctor in Textual pilots at 150x45 cells with fake
services. The selected Setup step is Hotkey. The Doctor report has nine OK
checks, one warning, a selected warning, and three synthetic warning rows.
The captures are `after-{setup,doctor}.{svg,txt,png}`. The before SVG and text
files came from the task 106 pilot captures. No microphone, system capture,
model, `live`, or `run` was used.

Approved board PNGs:

- Setup: `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/Setup.png`
- Doctor: `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/Doctor.png`

## Setup comparison

| Board element | Result | Comparison |
| --- | --- | --- |
| U-1 — wizard layout | Matches | A bordered six-step list sits left of the bordered selected-step detail panel. |
| U-2 — selected step | Matches | Setup and Hotkey use the bold accent `▶` marker with no fill, as task 107 requires. |
| U-3 — hotkey detail | Matches | The panel shows capture target, mode, hybrid threshold, general and cancel bindings, device, and test status. Fixture values differ from the board sample. The target uses a text row instead of the board's larger key callout. |
| U-4 — quick setup | Matches | The step panel says `quick: steps 1-3 only`. |
| U-5 — key hints | Differs | Existing hints also show `e edit` and `Q quick`; these actions remain available. Hints have no keycap fills under task 107. |
| U-6 — canvas and normal text | Overridden | Task 107 requires no painted background and terminal-default foreground. The hub no-background pilot passes. |

## Doctor comparison

| Board element | Result | Comparison |
| --- | --- | --- |
| D-1 — summary | Matches | The sidebar card shows OK, warning, and failure counts plus check time. The pilot shows 9 OK, 1 warning, 0 failures, checked 21:23. |
| D-2 — grouped checks | Matches | Input/audio and engine/desktop groups are bordered and side by side. The pilot shows all ten fixture checks. |
| D-3 — issue detail | Matches | The selected warning has a bordered detail/fix panel after `enter`. Before `enter`, the panel preserves the existing collapsed-details behavior. |
| D-4 — recent warnings | Matches | A separate bordered panel shows three safe, synthetic warning rows. |
| D-5 — selected check | Matches | The selected warning uses a bold accent `▶` marker with no fill. |
| D-6 — check states | Matches | The pilot shows OK and warning states, with counts that match the board example. |
| D-7 — key hints | Matches | Re-check, details, Setup fix, log, and copy hints remain. Keycap fills are omitted under task 107. |
| D-8 — canvas and normal text | Overridden | Task 107 requires no painted background and terminal-default foreground. The hub no-background pilot passes. |

The `test_hub_sections_dialogs_and_live_app_do_not_paint_backgrounds` pilot
checks rendered cells for both screens. The checked output has no painted
backgrounds outside Textual's scrollbar-thumb exception.
