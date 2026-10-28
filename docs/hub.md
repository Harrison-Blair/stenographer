<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Terminal hub

Run `stenographer` from a terminal to open the hub. It opens on Record and does
not start recording until you press `space`. If stdin or stdout is not a
terminal, the command prints help instead. The hub is a local, keyboard-driven
interface with three screens. The daemon and existing commands keep their
current behavior. In particular, `stenographer live` still opens its
standalone live app with its existing flags. See the [live guide](live.md).

## Screens and keys

Press `1`, `2`, or `3`, or click a row of the navigation list, to show a
screen. Keys `4` to `6` do nothing.

| Key | Screen | Purpose |
| --- | --- | --- |
| `1` | Record | Record microphone and system audio, and view the transcript. |
| `2` | Library | Review saved sessions, and transcribe audio files. |
| `3` | Settings | Edit settings by tab, and run the system checks. |

Each screen has a sidebar and one row of key hints at the bottom. The hint row
ends with `? help · q quit`. Press `?` to open a help overlay that lists every
key of the current screen; press `?` or `escape` to close it. Each control on
screen prints its key, for example `[r] Run again`, and a click on it does the
same as the key.

The sidebar shows, from top to bottom:

- **Navigation:** `1 Record`, `2 Library`, and `3 Settings`. The current screen
  has a bold `▶` marker. Record shows `● HH:MM:SS` while a recording runs and
  `Ⅱ HH:MM:SS` while it is paused. Library shows its entry count. Settings
  shows `N W` when the last check run has warnings and `N F` when it has
  failures.
- **Engine card:** the model (`bark-pro-int8`), a state line such as
  `ready · 2 queued` or `idle · unloaded`, the CPU use of the hub and its speech
  worker (`cpu app`), the CPU use of the system (`all`), the memory of the hub
  and its worker (`ram app`), and a 60-second CPU history. The card updates
  once per second. A gauge shows `—` before its first sample.
- **Context card:** a card that the current screen sets, for example the
  speakers of the recording or the size of the library.

Scrollbars stay visible. Their thin accent-colour thumbs are the only exception
to the no-background rule; tracks and corners stay transparent.

## Hub lifecycle

Record is idle when the hub opens. Press `space` to start recording; while a
session is active, `space` pauses or resumes it. Recording continues when you
change screens. The hub runs recording start, stop, and save work in the
background so the interface can remain responsive.

Press `q` or `ctrl+c` to quit. When a recording is active, the hub asks "Stop
recording and save before quitting?" Press `y`, `q`, or `ctrl+c` (or click
`[y] Save and quit`) to stop and save; press `n` or `escape` (or click
`[n] Keep recording`) to keep recording. When a Files job is running, the hub
asks before it cancels the job and quits. A cancelled Files job does not leave
a partial output file. If a start, stop, or save operation is still in
progress, wait for its status to finish before you send another quit key.

If Settings has unsaved changes, the hub asks whether to save, discard, or stay
before it leaves Settings or quits. A tab change inside Settings keeps the
changes and does not ask. A successful save keeps a timestamped
`config.toml.bak-<time>` backup and preserves comments and settings that the
editor does not know about.

## Record

Record has a REC panel, a MIC meter, a SYSTEM meter, the transcript, and a
`speakers` context card. Each state shows a glyph and a word, so it does not
depend on colour.

| State | REC panel | Keys |
| --- | --- | --- |
| Idle | `○ READY`, the microphone device, `[space] ● Record` | `space` record · `d` device · `m` mic · `s` system · `v` view |
| Recording | `● REC`, the elapsed clock, `started HH:MM`, `[enter] ■ Stop & save`, `[space] Ⅱ Pause` | `enter` stop & save · `space` pause · `m` mic · `s` system · `v` view · `r` rename |
| Paused | `Ⅱ PAUSED` and `[space] ▶ Resume` | as Recording, with `space` resume |
| Saved | `■ SAVED`, the final duration, `saved HH:MM`, the session ID, `[space] ● Record again`, `[o] Open in Library` | `space` record again · `o` open in Library · `d` device · `m` mic · `s` system · `v` view · `r` rename |

Press `enter` (or click `[enter] ■ Stop & save`) to stop and save. The hub
stays open. The save and the speaker relabel pass run in the background: the
transcript title shows `relabeling…` and the engine card shows
`relabeling N of M` until the pass ends. While it runs, the saved session is
busy: `[r] Rename… busy` shows in the speakers card, and `r` shows the notice
`session busy`. You can press `space` to record again while the pass runs, and
several stopped sessions can relabel at the same time. When the pass ends, the
transcript ends with a marker line such as
`── saved · 31 phrases · mic.flac 88 MB · system.flac 0.2 MB ──` (only the
audio files that exist). Press `o` to show the session in Library.

If you quit while a relabel pass runs, the hub asks "Relabel is still running.
Quit and keep the live labels?" Press `y` to skip each pass; the hub waits until
each session has saved its files, then quits. The saved session keeps the
labels that it had during the recording. Press `n` to keep the hub open.

Each meter shows 18 frequency bands in 8 rows, the band labels
`100 200 400 800 1k6 3k2 6k4`, the level and the 3-second peak in dBFS, and a
speech light (`● speech` or `○ quiet`) from the voice detector of the source.
While no recording runs, a meter shows a dotted grid: the MIC meter shows
`not recording` and the SYSTEM meter shows `captures the default output mix`.
Press `m` or `s` to turn a source on or off. During a recording, the key
changes the running session. Before a recording, the key chooses the sources
of the next recording; a source that is off shows `off · press m to enable` (or
`s`). System audio captures the current output mix, not separate applications.

Press `d` (or click `[d] change device…`) while no recording runs to choose the
input device. The dialog lists each input device and `Settings default`. The
choice shows in the MIC meter and applies to the next recordings until the hub
quits. It does not change `config.toml`; the Audio tab of Settings edits the
saved device.

The transcript opens in mixed view, with one time-ordered stream and speaker
labels. Press `v` (or click `[v] ▶ mixed  split`) to switch to split view,
where microphone and system lines appear in separate, captioned columns in time
order. Use `up` and `down` to scroll one line, `pageup` and `pagedown` to scroll
one page, and `home` and `end` to move to the top and bottom. The mouse wheel
also scrolls the transcript. New lines stay in view while the transcript is at
the bottom. If you scroll up, refreshes do not move the view; press `end` or
scroll to the bottom to follow new lines again.

The `speakers` card lists each speaker with its talk time, the count of failed
phrases when there are any, and `[r] Rename…`. Press `r` (or click the card) to
open the Rename speaker dialog: choose the speaker, type the new name, and press
`enter` (or click `[enter] Rename`); `escape` cancels. During a recording, the
rename changes the live labels. On a saved session, the rename writes a new
transcript revision of that session.

When `live.diarize_mic` is on in Settings (Live tab), a new recording labels microphone
speakers `Room 1`, `Room 2`, and so on, apart from the system speakers
(`Speaker 1`, ...). `r` lists room speakers with the system speakers. The
setting applies when a recording starts; Record has no toggle for it. With the
setting off, microphone lines are `You`. See
[separate the speakers in a room](live.md#separate-the-speakers-in-a-room) for
its limits.

When you stop and save a session, stenographer runs a batch speaker-label pass
on the saved system phrases, and separately on the microphone phrases when
microphone diarization is on, and stores the revised labels in a new transcript
revision. This pass also runs when you confirm quit during a recording. Speaker
labels are similarity estimates, not reliable identity checks. A minor voice
gets its own label only if it has at least 15 seconds of phrases that are each
at least 2 seconds long within a 30-second window and at least two-thirds of
its speech in those sustained phrases, or if it has at least 20% of the top
speaker's speech time. Otherwise, stenographer merges that voice into the most
similar voice. Short or sparse phrases can therefore remain under another
speaker's label.

Live session audio and transcripts are saved only in the session folder. Logs
and analytics do not contain audio or transcript text. See [saved session
files and privacy](live.md#saved-session-files).

## Library

Library has a list on the left and the detail of the selected entry on the
right. The list holds saved recordings, file sessions, and file jobs that are
not finished, newest first. Its columns are `date`, `dur`, `kind` (`rec` or
`file`), `spk` (speaker count), and `labels`:

- **Recording:** `labels` is `live` for live speaker labels, `relabeled` after
  the relabel pass or a re-diarize, or `! interrupted` when the recording
  stopped without a clean save.
- **File session:** `labels` is the name of the source file.
- **File job:** `dur` shows `queued` or the percent done, and `labels` shows the
  source file name. A failed job shows `× failed`; press `delete` to remove its
  row. When a job finishes, its row becomes the session row and stays
  selected.
- **Revision job:** a job that writes a new revision of a listed session shows
  `queued` or its percent in the `dur` cell of that session row.

The list updates when a job ends and when a recording is saved, and it keeps
the selected entry. The active recording does not appear until it is saved.
The context card shows the entry count, the audio size, and the sessions
folder; the navigation row shows the entry count.

Press `/` to search titles and transcripts; the search ignores case and runs in
the background. A job row matches by its source file name. Press `escape` to
clear the search.

The detail shows the date, time, duration, and kind, the label state, each
speaker's talk time, the microphone and system activity of a recording, and
the transcript. Each action is a button that prints its key:

| Key | Action |
| --- | --- |
| `n` | Open Files to transcribe audio files. |
| `up` / `down` | Select the previous or next entry. |
| `p` | Play or stop the session audio with `pw-play`. A file session plays its source file. |
| `r` | Rename a speaker of the session. |
| `d` | Re-diarize the session. A file session cannot: use Re-transcribe. |
| `t` | Re-transcribe the session. |
| `x` | Export the transcript. |
| `delete` | Delete the session after confirmation. On a queued or running job, cancel it after confirmation. |
| `pageup` / `pagedown`, `home` / `end` | Scroll the transcript. |

While a re-diarize, re-transcribe, rename, delete, or file job changes a
session, that session is busy: its Rename, Re-diarize, Re-transcribe, and
Delete buttons show `busy` and do nothing, and a second change shows the
notice `session busy`. On a session row with a running revision job, `delete`
cancels the job.

`x` opens the Export dialog. Press `tab` or click a format to choose `md`,
`jsonl`, `srt`, or `txt`, and type the folder (default `~/Documents`). Press
`enter` to export or `escape` to cancel. The notice shows the path of the
exported file.

Re-diarization and re-transcription write new transcript revisions and keep
previous revisions. Re-labeling uses the same speaker similarity limits as the
Record screen. Re-diarization relabels microphone lines as `Room N` speakers only
for a session recorded with microphone diarization (`"diarize_mic": true` in its
`session.json`). For other sessions, including older ones, it relabels system
lines only and microphone lines stay `You`. `r` can rename room speakers.

### Files

Press `n` in Library to open Files in the screen body; press `escape` to
return to the Library list. Files has a browser, transcription options, a job
queue, and a result preview.
The browser lists WAV, FLAC, OGG, MP3, Opus, AAC, M4A, MP4, MKV, WebM, and WMA
files. Files that `soundfile` can read use that library. M4A and AAC files use
the system `ffmpeg` executable; other files that `soundfile` cannot read also
use `ffmpeg`. Stenographer does not bundle FFmpeg. Install it with your system
package manager. The Checks tab reports when `ffmpeg` is missing, and a file job that
needs it cannot start without it.

The browser opens in the folder where Live saves recordings:
`$XDG_DATA_HOME/stenographer/sessions/`, or
`~/.local/share/stenographer/sessions/` when `XDG_DATA_HOME` is unset. Each
session folder holds `mic.flac` and `system.flac`. When that folder does not
exist yet, the browser opens in your home folder. Select `..` to move up from
either one; the browser title shows the current folder.

Select one or more files in the browser and press `enter` to queue them. Jobs
run one at a time in the background. The queue shows each job's state, stage,
progress, and estimated time remaining. Select a job to see its transcript
preview. Press `x` while the queue has focus to cancel the selected job.

Each job saves its result in the sessions folder, next to your recordings:

- **Another file:** the job makes a new session folder named by the UTC time
  the job started, for example `20261027T153000Z` (when that name exists, it
  adds one second). The folder holds a private copy of the file as
  `source.<ext>`, `transcript.jsonl`, `transcript.md`, and `session.json` with
  `"kind": "file"`, the original file name, and the duration. `<ext>` is the
  original suffix in lower case when it has 1 to 8 letters or digits, else
  `bin`.
- **`mic.flac` or `system.flac` of a recording:** the job saves a new
  transcript revision of that recording. The revision holds the new lines of
  that source and the current lines of the other source, ordered by start
  time. New speakers get IDs such as `mic-file-r3-1` and the labels `Room 1`
  (mic) or `Speaker 1` (system); without diarization, mic lines are `You`.
  Earlier renames of the replaced source do not carry over.
- **`source.<ext>` of a file session:** the job saves a new transcript
  revision that replaces all lines.

A path outside the sessions folder, a symlink that leads out of it, or a file in
a subfolder of a session makes a new session. A cancelled or failed job
removes the folder that it made, and a revision job that stops leaves the
session unchanged. When the session changes while a revision job runs (for
example, a speaker rename), the job fails and keeps the newer revision.
Earlier results in the old `files/` folder stay where they are; the hub does
not read, move, or delete them.

The options are:

- **Diarize:** identify and label speakers. This is on by default.
- **Speaker count:** choose `auto` or a positive number. `auto` is the default.
  A number requests a fixed speaker count for that Files job.
- **Refine:** apply the configured text-refinement service. This is off by
  default for Files jobs.

Press `tab` to move focus between the browser, queue, and options. In the
browser, press `/` to search, `space` to select a file, and `enter` to open a
folder or queue the selected files. In Options, press `o` to open or close the
panel; use the arrow keys to choose a setting and `enter` or `space` to edit
it. Speaker count accepts `auto` or a positive integer.

## Settings

Settings has five tabs: General, Audio, Recognition, Live, and Checks. Press
`left` and `right`, or click a tab, to change the tab. A `▶` marks the active
tab. The first four tabs edit
`config.toml`:

| Tab | Settings |
| --- | --- |
| General | hotkey, sound and overlay feedback, update check, log level, delivery, and analytics |
| Audio | input device, minimum speech level, maximum recording length, and spectrum floor |
| Recognition | `asr.idle_unload_seconds`, `asr.cpu_threads`, and the refine settings |
| Live | `live.diarize_mic` |

Each tab shows compact key/value rows. A `●` marks values that differ from
their defaults. The selected key's description and default appear at the
bottom of the panel. The context card shows the config path and the count of
unsaved changes. Recognition holds the one shared set of ASR settings for
dictation, Record, and Files. Model downloads are explicit. Run
`stenographer model download --asr` to build the speech model; see
[build the speech model](usage.md#build-the-speech-model).

| Key | Action |
| --- | --- |
| `left` / `right` | Select a tab. |
| `up` / `down` | Select a setting. |
| `enter` | Edit the selected setting. |
| `u` | Undo the last edit. |
| `shift+d` | Reset the selected setting to its default. |
| `/` | Search setting names in every tab. |
| `ctrl+s` | Save changes and keep a timestamped backup. |

Settings apply to new sessions and jobs. Work that is already running keeps
its current settings.

### Checks

The Checks tab runs the system checks the first time it opens. It groups the
capability checks and shows details and fixes for the selected check. The
context card shows `N pass · N warn · N fail` and the time of the last run, and
the tab label shows `●N` when the last run has warnings or failures. New
optional checks appear as warnings and do not change the existing
`stenographer doctor` exit status. Recent warnings are shown without
transcript text.

| Key | Action |
| --- | --- |
| `up` / `down` | Select a check. |
| `enter` | Show or hide the details of the selected check. |
| `r` | Run the checks again. |
| `f` | Fix: open the related setting, or offer the model download. |
| `t` | Test the area of the selected check. |
| `l` | Open the log. |
| `c` | Copy the check report. |
| `m` | Start a model download after confirmation. |
| `shift+d` | Write the default configuration. |

The microphone test lists available devices and does not capture audio. The
sound test plays a preview. The hub does not start or restart the system
service. The `stenographer setup` and `stenographer doctor` commands do not
change.
