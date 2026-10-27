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

Record has a REC panel with elapsed time and MIC and SYSTEM panels with the
device, waveform meter, and dBFS level. The context card lists the speakers,
the count of failed phrases when there are any, and `[r] Rename…`. The
transcript opens in mixed view, with one time-ordered stream and speaker
labels. Press `v` to switch to split view, where microphone and system lines
appear in separate, captioned columns in time order. Press `v` again to return
to mixed view. Use `up` and `down` to scroll one line, `pageup` and `pagedown`
to scroll one page, and `home` and `end` to move to the top and bottom. The
mouse wheel also scrolls the transcript. New lines stay in view while the
transcript is at the bottom. If you scroll up, refreshes do not move the view;
press `end` or scroll to the bottom to follow new lines again. Press `m` to
toggle microphone input, `s` to toggle system audio, and `r` to rename a
speaker. System audio captures the current output mix, not separate
applications.

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

Library lists saved sessions. The context card shows the entry count, the
audio size, and the sessions folder. The saved session list and
selected-session detail use separate bordered panels. The list shows each
session's duration and speaker count. Select a session with the up and down
arrows. The detail view shows each speaker's talk time, microphone and system
activity, whether labels were revised, and the transcript. The active recording
does not appear in this list until it has been saved.

| Key | Action |
| --- | --- |
| `n` | Open Files to transcribe audio files. |
| `p` | Play or stop session audio with `pw-play`. |
| `d` | Re-diarize the saved session. |
| `t` | Re-transcribe the saved session. |
| `r` | Rename a speaker in the selected session. |
| `x` | Export the transcript as `md`, `jsonl`, `srt`, or `txt`. |
| `delete` | Delete the selected session after confirmation. |

Re-diarization and re-transcription write new transcript revisions and keep
previous revisions. Re-labeling uses the same speaker similarity limits as the
Record screen. Re-diarization relabels microphone lines as `Room N` speakers only
for a session recorded with microphone diarization (`"diarize_mic": true` in its
`session.json`). For other sessions, including older ones, it relabels system
lines only and microphone lines stay `You`. `r` can rename room speakers.

### Files

Press `n` in Library to open Files in the screen body; press `escape` to
return to the session list. Files has a browser, transcription options, a job
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

Each row shows a `●` slot, the setting name, its control, and help. A `▶`
marks the selected row. The controls are:

| Control | Example | Edit |
| --- | --- | --- |
| Toggle | `(●) on`, `( ) off` | `space` or `enter` flips it. |
| Number | `900 s` | `enter` opens an input in the row; it refuses letters. |
| Text | `http://127.0.0.1:11434` | `enter` opens an input in the row. |
| Choice | `hybrid ▾` | `enter` opens the list of allowed values. |
| Device | `Default input ▾` | `enter` lists the devices of the sound server. |
| List | `[enter] Edit list… 3 terms` | `enter` opens the Vocabulary editor. |

While an input in a row has focus, letters go to the input. `enter` keeps the
value, `escape` cancels it, `tab` keeps it and selects the next row, and
`ctrl+s` keeps it and saves.

A `●` marks a row whose value differs from the saved file, not from the
default. The help of the selected row shows the default. The context card
shows the config file, `● N unsaved changes`, and the newest
`config.toml.bak-<time>` backup with its time. Below the rows, `[ctrl+s] Save N
changes`, `[u] Undo`, `[D] Reset row`, and `Discard all` act on the draft;
Discard all asks first. Click a row to select it, and click it again to edit
it. Recognition holds the one shared set of ASR settings for dictation,
Record, and Files. Model downloads are explicit. Run
`stenographer model download --asr` to build the speech model; see
[build the speech model](usage.md#build-the-speech-model).

The Vocabulary row (`refine.vocabulary`) opens a list editor. Press `a` to
add a term, `e` to edit the selected term, and `del` to delete it. In the
term input, `enter` keeps the term and `escape` closes the input. A term is
trimmed, is not empty, has at most 64 characters, and does not repeat another
term in any letter case; the list holds at most 200 terms. The editor refuses
a term that breaks a rule and names the rule. `enter` Done makes the list an
unsaved change of Settings; `escape` cancels.

| Key | Action |
| --- | --- |
| `left` / `right` | Select a tab. |
| `up` / `down` | Select a setting. |
| `enter` | Edit the selected setting. |
| `space` | Flip the selected toggle. |
| `u` | Undo the last edit. |
| `shift+d` | Reset the selected setting to its default. |
| `/` | Search setting names in every tab; `escape` clears the search. |
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
