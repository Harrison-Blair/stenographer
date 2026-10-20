# Hub board audit

## Method and shared rules

The boards define layout and content. They do not define exact colours, sizes, or fonts. The user's no-background rule overrides every board fill. This includes the dark canvas, selected rows, speaker chips, keycaps, and status fills. The selected item must use bold accent text and a `▶` marker with no fill. Normal text must use the terminal foreground.

I rendered the current `HubApp` in a Textual pilot at 150x45 cells. The pilot used fake services and synthetic fixture lines. It did not access a microphone, system capture, model, `live`, or `run`. SVG and plain-text renders are beside this file. The run used Textual 8.2.8 from `/home/penguin/source/stenographer/.venv`; the worktree has no `.venv` directory. In this version, `CSS` strings on widget classes do not apply as widget styles. The pilot showed empty computed borders for the Files and Sessions child widgets. Their panels therefore render without the declared borders and sizing rules. Screen-subclass CSS for ConfigPrompt and QuitConfirm applies, as does child styling in RenameDialog. The `App.CSS` rules apply.

Severity values: `layout`, `content`, `key hint`, and `cosmetic`.

## Live

Boards: `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/StenoB.dc.html` (mixed), `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/LiveSplit.dc.html` (split).

| Board element | Board (what it shows and where) | Hub now | Gap (missing / different / extra / ok) | Severity |
| --- | --- | --- | --- | --- |
| L-1 Shell and engine card | Sidebar navigation plus separate engine, queue, failed-count, and CPU card (`StenoB.dc.html:18-35`). | Sidebar has navigation only. Engine, queue, failed count, and CPU appear as text inside Live. `src/stenographer/cli/hub/app.py:184-194`, `src/stenographer/cli/hub/app.py:264-280`. | different | layout |
| L-2 Selected section | Selected row is accent bold; the board fill is overridden by the no-background rule (`StenoB.dc.html:21-28`). | Row uses `>` and normal text. It has no `▶`, accent, or bold style (`src/stenographer/cli/hub/app.py:251-265`). | different; board fill, overridden by the no-background rule | cosmetic |
| L-3 REC panel | REC label and large elapsed time in its own top-row panel (`StenoB.dc.html:37-41`). | REC is one section of a vertical ASCII drawing inside the single Live `Static` (`src/stenographer/cli/hub/live_view.py:30-37`, `src/stenographer/cli/hub/app.py:269-280`). | different | layout |
| L-4 MIC panel and meter | MIC source, device, waveform-style meter, and dBFS in its own top-row panel (`StenoB.dc.html:42-46`). | MIC data is in a vertical text block. The meter has five level cells, not a waveform (`src/stenographer/cli/hub/live_view.py:39-57`). | different | layout |
| L-5 SYSTEM panel and meter | SYSTEM source, device, waveform-style meter, and dBFS in its own top-row panel (`StenoB.dc.html:47-51`). | SYSTEM data is in a vertical text block. The meter has five level cells, not a waveform (`src/stenographer/cli/hub/live_view.py:39-57`). | different | layout |
| L-6 Transcript and speaker chips | One transcript panel with timestamps, speaker chips, and lines (`StenoB.dc.html:53-60`). Chip fills are overridden by the no-background rule. | Lines show timestamp, `[label]`, and text in plain `Static` content. There is no transcript panel or bold accent chip treatment (`src/stenographer/cli/hub/live_view.py:60-78`, `src/stenographer/cli/hub/app.py:269-280`). | different; board chip fills, overridden by the no-background rule | layout |
| L-7 Key hints | Shows pause, source toggles, view, rename, stop/save, and section keys (`StenoB.dc.html:61-69`). Keycap fills are overridden by the no-background rule. | Shows pause/resume, source toggles, view, rename, and stop/save. It omits `1-6 sections` (`src/stenographer/cli/hub/app.py:323-324`). | missing | key hint |
| L-8 Canvas and normal text | Dark canvas and light text (`StenoB.dc.html:18`). The canvas fill is overridden by the no-background rule; normal text must use the terminal foreground. | The screen paints `#0b0d12` and sets text to `#e3e6ec` (`src/stenographer/cli/hub/app.py:93-97`). | different; no-background rule violation | cosmetic |
| LS-1 Transcript columns | Time column plus two named columns, `MIC · what you said` and `SYSTEM · everyone else` (`LiveSplit.dc.html:53-62`). | Text contains `time | MIC | SYSTEM`; source lines are formatted into fixed-width text fields, without the board's column captions (`src/stenographer/cli/hub/live_view.py:66-72`). | different | layout |
| LS-2 Empty-source cells | A dot marks the source with no line at each time (`LiveSplit.dc.html:57-61`). | The empty source field is blank (`src/stenographer/cli/hub/live_view.py:68-72`). | different | content |
| LS-3 Speaker labels | Speaker chips identify each line (`LiveSplit.dc.html:57-61`). Chip fills are overridden by the no-background rule. | Labels appear as plain `[label]` text (`src/stenographer/cli/hub/live_view.py:68-72`). | different; board chip fills, overridden by the no-background rule | cosmetic |
| LS-4 Shared Live header and hints | Keeps the REC, MIC, SYSTEM, and key-hint areas from the mixed board (`LiveSplit.dc.html:18-52,64-72`). | These areas use the same vertical text rendering as mixed Live; key hints omit `1-6 sections` (`src/stenographer/cli/hub/live_view.py:30-57`, `src/stenographer/cli/hub/app.py:323-324`). | different | layout |

## Files

Board: `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/Files.dc.html`.

| Board element | Board (what it shows and where) | Hub now | Gap (missing / different / extra / ok) | Severity |
| --- | --- | --- | --- | --- |
| F-1 Shell and engine card | Sidebar plus engine, model, profile, and CPU card (`Files.dc.html:18-35`). | Sidebar contains only the six sections. No engine card appears on Files (`src/stenographer/cli/hub/app.py:184-194`, `src/stenographer/cli/hub/app.py:251-265`). | missing | layout |
| F-2 Main panels | Browser left; options and queue right; preview below (`Files.dc.html:36-65`). | The widgets are composed in that order. The Files widget `CSS` rules are inactive in the pilot, so its declared borders and proportions do not render (`src/stenographer/cli/hub/files_view.py:35-78`, `src/stenographer/cli/hub/files_view.py:113-130`). | different | layout |
| F-3 Selected file | Files navigation row and selected file row have highlights (`Files.dc.html:21-27,39-44`); each is a board fill, overridden by the no-background rule. | The row uses `▸` without bold accent styling; it does not use `▶` (`src/stenographer/cli/hub/files_view.py:287-310`). | different; board fill, overridden by the no-background rule | cosmetic |
| F-4 Options | Shows diarize, speaker count, refine, output format, and output folder (`Files.dc.html:48-54`). | All five settings appear. `refine` is rendered as `[ ] on`, and the output choices are one slash-separated row (`src/stenographer/cli/hub/files_view.py:313-331`). | different | content |
| F-5 Queue progress | Shows percentage, a progress bar, ETA, and completed/current/upcoming stages (`Files.dc.html:54-58`). | Each job shows state, one stage, percent, and ETA. No progress bar or stage checklist appears (`src/stenographer/cli/hub/files_view.py:333-350`). | different | content |
| F-6 Preview | Shows a titled result preview with timestamps, speaker chips, and transcript lines (`Files.dc.html:60-65`). Chip fills are overridden by the no-background rule. | Preview lines use `[label]` text. The border title is only `preview`; the file stem is the first body line (`src/stenographer/cli/hub/files_view.py:122-130`, `src/stenographer/cli/hub/files_view.py:352-370`). | different; board chip fills, overridden by the no-background rule | content |
| F-7 Key hints | Shows queue, options, cancel, open result, and section keys (`Files.dc.html:66-72`). Keycap fills are overridden by the no-background rule. | Shows queue, options, cancel, and folder. It omits section keys and describes `e` as `folder`, not `open result` (`src/stenographer/cli/hub/app.py:325-329`). | different | key hint |
| F-8 Canvas and normal text | Dark canvas and light text (`Files.dc.html:18`). The canvas fill is overridden by the no-background rule; normal text must use the terminal foreground. | The screen paints `#0b0d12` and sets text to `#e3e6ec` (`src/stenographer/cli/hub/app.py:93-97`). | different; no-background rule violation | cosmetic |

## Sessions

Board: `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/Sessions.dc.html`.

| Board element | Board (what it shows and where) | Hub now | Gap (missing / different / extra / ok) | Severity |
| --- | --- | --- | --- | --- |
| S-1 Storage summary | Storage card sits below the sidebar and shows count and audio size (`Sessions.dc.html:29-33`). | Storage count and size appear in a narrow column beside the list, not in the sidebar (`src/stenographer/cli/hub/sessions_view.py:69-76`, `src/stenographer/cli/hub/sessions_view.py:145-155`). | different | layout |
| S-2 Saved list | Sessions navigation row and selected session row have highlights (`Sessions.dc.html:21-27,35-42`); each is a board fill, overridden by the no-background rule. | The list is a child of `SessionsPanel`. Its declared widths and borders are inactive in the pilot. Selection uses `▸`, not bold accent `▶` (`src/stenographer/cli/hub/sessions_view.py:17-54`, `src/stenographer/cli/hub/sessions_view.py:69-76`, `src/stenographer/cli/hub/sessions_view.py:156-167`). | different; board fill, overridden by the no-background rule | layout |
| S-3 Session detail | Separate detail panel shows label status, talk time, mic/system activity, and transcript with speaker chips (`Sessions.dc.html:43-56`). Chip fills are overridden by the no-background rule. | The same information appears as text in one child widget. There are no colored/bold speaker chips (`src/stenographer/cli/hub/sessions_view.py:185-201`). | different; board chip fills, overridden by the no-background rule | layout |
| S-4 Panel borders | List, storage, and detail each have a border (`Sessions.dc.html:29-56`). | Session widget borders and sizes come from `SessionsPanel.CSS`, which did not apply in the pilot (`src/stenographer/cli/hub/sessions_view.py:17-54`). | missing | layout |
| S-5 Key hints | Shows playback, re-diarize, re-transcribe, rename, export, and delete (`Sessions.dc.html:58-65`). | The same actions appear (`src/stenographer/cli/hub/app.py:318-322`). | ok | key hint |
| S-6 Canvas and normal text | Dark canvas and light text (`Sessions.dc.html:18`). The canvas fill is overridden by the no-background rule; normal text must use the terminal foreground. | The screen paints `#0b0d12` and sets text to `#e3e6ec` (`src/stenographer/cli/hub/app.py:93-97`). | different; no-background rule violation | cosmetic |

## Config

Board: `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/Config.dc.html`. Decision 15 replaces its two profile columns with one column of ASR settings.

| Board element | Board (what it shows and where) | Hub now | Gap (missing / different / extra / ok) | Severity |
| --- | --- | --- | --- | --- |
| C-1 Sidebar status | Sidebar card shows `config.toml` and an unsaved-change count (`Config.dc.html:29-33`). | Config renders the file path and only `yes/no` for unsaved changes in the main content (`src/stenographer/cli/hub/config_view.py:216-220`). | different | content |
| C-2 Group selector | Config navigation row and selected ASR group have highlights (`Config.dc.html:21-27,35-46`); each is a board fill, overridden by the no-background rule. | Group names appear inline above the settings. There is no separate selector widget; the active group is bracketed (`src/stenographer/cli/hub/config_view.py:212-224`). | different; board fill, overridden by the no-background rule | layout |
| C-3 ASR settings | Decision 15 requires one column of shared ASR settings. The board's two profile columns are out of date (`Config.dc.html:47-63`). | Config shows one list of settings, defaults, and help text (`src/stenographer/cli/hub/config_view.py:206-236`). | ok | content |
| C-4 Recent-line context | Board shows a context setting (`Config.dc.html:49-57`). | No `context from recent lines` key appears in the ASR settings rendered from `Config` (`src/stenographer/cli/hub/config_view.py:206-236`). Decision 12 keeps this setting gated on benchmark results and the user's choice. | missing; blocked by decision 12 | content |
| C-5 Hotwords and benchmark note | Board gives hotwords a separate value area and shows a beam-size note (`Config.dc.html:59-64`). The value area's fill is a board fill, overridden by the no-background rule. | Hotwords appear as a regular setting row; beam-size help contains benchmark figures (`src/stenographer/cli/hub/config_view.py:20-42`, `src/stenographer/cli/hub/config_view.py:227-236`). | different | content |
| C-6 Key hints | Shows edit, save, undo, reset, and search (`Config.dc.html:66-72`). Keycap fills are overridden by the no-background rule. | These actions appear, with extra group/key navigation hints (`src/stenographer/cli/hub/app.py:310-313`). | ok | key hint |
| C-7 Canvas and normal text | Dark canvas and light text (`Config.dc.html:18`). The canvas fill is overridden by the no-background rule; normal text must use the terminal foreground. | The screen paints `#0b0d12` and sets text to `#e3e6ec` (`src/stenographer/cli/hub/app.py:93-97`). | different; no-background rule violation | cosmetic |

## Setup

Board: `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/Setup.dc.html`.

| Board element | Board (what it shows and where) | Hub now | Gap (missing / different / extra / ok) | Severity |
| --- | --- | --- | --- | --- |
| U-1 Wizard layout | Six-step list on the left and selected-step detail on the right (`Setup.dc.html:30-57`). | Steps and detail are a single text list inside the section `Static` (`src/stenographer/cli/hub/setup_wizard.py:61-89`, `src/stenographer/cli/hub/app.py:281-283`). | different | layout |
| U-2 Selected step | Setup navigation row and selected hotkey step have highlights (`Setup.dc.html:21-27,33-42`); each is a board fill, overridden by the no-background rule. | Uses `▸` in unstyled text rather than bold accent `▶` (`src/stenographer/cli/hub/setup_wizard.py:64-71`). | different; board fill, overridden by the no-background rule | cosmetic |
| U-3 Hotkey detail | Shows capture target, mode, threshold, general binding, cancel binding, device, and test status (`Setup.dc.html:43-56`). | Shows the selected setting, description, and test string. The other hotkey controls and capture target are absent (`src/stenographer/cli/hub/setup_wizard.py:75-84`). | missing | content |
| U-4 Quick setup | Sidebar says the short path uses steps 1-3 (`Setup.dc.html:40-42`). | The board's 6-step path appears. The key hints also offer `Q quick` (`src/stenographer/cli/hub/setup_wizard.py:61-89`, `src/stenographer/cli/hub/app.py:314-315`). | ok | content |
| U-5 Key hints | Shows next, back, test, skip, and defaults (`Setup.dc.html:58-64`). Keycap fills are overridden by the no-background rule. | The same actions appear; the hint also shows `Q quick` (`src/stenographer/cli/hub/app.py:314-315`). | ok | key hint |
| U-6 Canvas and normal text | Dark canvas and light text (`Setup.dc.html:18`). The canvas fill is overridden by the no-background rule; normal text must use the terminal foreground. | The screen paints `#0b0d12` and sets text to `#e3e6ec` (`src/stenographer/cli/hub/app.py:93-97`). | different; no-background rule violation | cosmetic |

## Doctor

Board: `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/Doctor.dc.html`.

| Board element | Board (what it shows and where) | Hub now | Gap (missing / different / extra / ok) | Severity |
| --- | --- | --- | --- | --- |
| D-1 Summary | Sidebar summary card shows counts and check time (`Doctor.dc.html:29-33`). | Sidebar shows only a warning/failure count beside Doctor. The report count is at the top of the main text (`src/stenographer/cli/hub/app.py:254-265`, `src/stenographer/cli/hub/doctor_view.py:53-77`). | different | layout |
| D-2 Grouped checks | Two side-by-side groups show checks (`Doctor.dc.html:35-53`). The warning row has a board fill, overridden by the no-background rule. | Both groups are rendered one after the other in a single text widget (`src/stenographer/cli/hub/doctor_view.py:53-77`). | different | layout |
| D-3 Issue detail | Warning has its own bordered detail/fix panel (`Doctor.dc.html:51-57`). | Selected warning details and fix appear inline in the report text (`src/stenographer/cli/hub/doctor_view.py:67-72`). | different | layout |
| D-4 Recent warnings | Separate bordered log panel shows recent warning rows (`Doctor.dc.html:58-63`). | Recent warnings follow the checks in the same report text (`src/stenographer/cli/hub/doctor_view.py:73-76`). | different | layout |
| D-5 Selected check | Doctor navigation row and selected check have highlights (`Doctor.dc.html:21-27,45-52`); each is a board fill, overridden by the no-background rule. | Uses `>` without bold accent `▶` (`src/stenographer/cli/hub/doctor_view.py:58-65`). | different; board fill, overridden by the no-background rule | cosmetic |
| D-6 Check states | Board example shows OK and warning states (`Doctor.dc.html:38-52`). | Pilot uses one fake OK, one fake warning, and one fake failure to meet the audit render request. The report renders all three statuses (`src/stenographer/cli/hub/doctor_view.py:53-77`). | ok | content |
| D-7 Key hints | Shows re-check, details, Setup fix, log, and copy (`Doctor.dc.html:64-70`). Keycap fills are overridden by the no-background rule. | The same actions appear (`src/stenographer/cli/hub/app.py:316-317`). | ok | key hint |
| D-8 Canvas and normal text | Dark canvas and light text (`Doctor.dc.html:18`). The canvas fill is overridden by the no-background rule; normal text must use the terminal foreground. | The screen paints `#0b0d12` and sets text to `#e3e6ec` (`src/stenographer/cli/hub/app.py:93-97`). | different; no-background rule violation | cosmetic |

## Background inventory

Scope: background sources in the hub and the Textual 8.2.8 defaults used by its screens and widgets. Paths under `textual/` refer to `/home/penguin/source/stenographer/.venv/lib/python3.14/site-packages/textual/`.

| Source | What it paints or can paint | Status in the pilot |
| --- | --- | --- |
| `src/stenographer/cli/hub/app.py:93-97` | `Screen` sets background `#0b0d12` and text color `#e3e6ec`. | Active on each rendered screen. Both conflict with the user's no-background and default-foreground rules. |
| `textual/app.py:305-312` | Textual `App.DEFAULT_CSS` sets `App` background to `$background`; ANSI mode uses `ansi_default`. | Framework default. The hub's explicit screen rule paints over the screen area. |
| `textual/screen.py:174-192` | `Screen.DEFAULT_CSS` sets `$background`; inline-screen borders use that color, text selection uses `$screen-selection-background`, and ANSI mode uses `ansi_default`. | Framework defaults. The standard hub screen has the explicit app-level color. |
| `textual/screen.py:2164-2171` | `ModalScreen.DEFAULT_CSS` declares `$background 60%`; ANSI mode uses transparent. | Hub CSS overrides the root background for all captured dialogs: ConfigPrompt and QuitConfirm use 75% opacity; RenameDialog uses the hub Screen background. |
| `src/stenographer/cli/hub/config_dialog.py:18-29` | ConfigPrompt screen uses `$background 75%`; prompt panel uses `$surface`. | Active in the pilot. The screen-subclass stylesheet applies. |
| `src/stenographer/cli/hub/dialogs.py:24-35` | QuitConfirm screen uses `$background 75%`; dialog panel uses `$surface`. | Active in the pilot. The screen-subclass stylesheet applies. |
| `src/stenographer/cli/live/rename_dialog.py:18-27` | Rename dialog panel uses `$surface`. | Active in the pilot. The Screen-subclass stylesheet applies to the child panel. The root screen uses the hub's `Screen` background. |
| `textual/widget.py:290-308` | Widget defaults include `$scrollbar-background`, hover/active variants, and `background: transparent`. | Scrollbar fills can paint when shown. The widget body default is transparent. |
| `textual/widgets/_button.py:49-113,125-185,188-229` | Button defaults use `ansi_default`, `$surface`, `$primary`, `$success`, `$warning`, and `$error`, including hover and active fills. | Applies to buttons in the hub prompts (`src/stenographer/cli/hub/dialogs.py:53-58`, `src/stenographer/cli/hub/config_dialog.py:55-63`, `src/stenographer/cli/live/rename_dialog.py:44-46`). |
| `textual/widgets/_input.py:186-218,229-234` | Input uses `$surface`; focus, cursor, selection, invalid, and ANSI styles can paint backgrounds. | Applies to text inputs in ConfigPrompt and RenameDialog. |
| `textual/widgets/_select.py:180-211,303-335` | SelectCurrent and the option overlay use `$surface`; focus tint can paint. | Applies to the speaker selector in RenameDialog (`src/stenographer/cli/live/rename_dialog.py:38-46`). |
| `textual/widgets/_toast.py:36-55` | Toast uses `$panel-lighten-1`; ANSI mode uses `$ansi-background`. | Hub actions call `notify`; pilot notifications were disabled for deterministic captures. |
| `textual/app.py:341-345` | Maximized view uses a right hatch in `$panel`. | Conditional Textual default; the hub does not maximize widgets in the captures. |
| `textual/theme.py:70-91` | Textual's default `textual-dark` theme supplies `$background`, `$surface`, and related colors. | Resolves framework variables. The user rule requires transparent backgrounds instead of these fills. |

No Hub `Rich` styles with `on <colour>` or `reverse` were found. Hub `Static` widgets use `markup=False`; `SessionsPanel.render()` returns an empty unstyled `Text` (`src/stenographer/cli/hub/app.py:186-194`, `src/stenographer/cli/hub/sessions_view.py:66-67`). Textual's ANSI-light input theme has a `reverse` cursor style (`textual/theme.py:498`), but that theme is not active in this pilot.

## Proposed fix split

Task 107, `hub-no-background`, owns the shared color and selected-item rules. The screen tasks below follow it where their gaps need those rules. There is one task per screen. Live is first. Each task stays within its screen and the listed gap IDs.

| Order | Task | Gap IDs | Gaps that depend on task 107 | Other dependency |
| --- | --- | --- | --- | --- |
| 1 | Live mixed and split layout and content. | L-1, L-3-L-7, LS-1-LS-2, LS-4. | L-2, L-6, L-8, LS-3. | None. |
| 2 | Files panels, queue, preview, and hints. | F-1-F-2, F-4-F-7. | F-3, F-6, F-8. | None. |
| 3 | Sessions panels, detail, and hints. | S-1, S-3-S-5. | S-2, S-3, S-6. | None. |
| 4 | Config group and settings presentation. | C-1, C-2, C-5. | C-2, C-5, C-7. | C-4 waits for the decision-12 benchmark and user choice. Keep the one-column design from decision 15 (C-3). |
| 5 | Setup wizard layout and selected-step detail. | U-1, U-3. | U-2, U-6. | None. |
| 6 | Doctor groups, issue detail, and warning panel. | D-1-D-4. | D-2, D-5, D-8. | None. |

Task 107 also covers the shared `Background inventory` findings and the no-background rule across all screens. `C-4` is not a no-background gap and stays blocked on the benchmark decision.
