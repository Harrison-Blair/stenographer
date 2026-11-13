<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Terminal hub

Run `stenographer` from a terminal to open the hub. It opens on Record and does
not start recording until you press `space`. If stdin or stdout is not a
terminal, the command prints help instead. The hub is a local, keyboard-driven
interface with three screens. The daemon and existing commands keep their
current behavior.

While the hub is open, only the hub writes to the terminal. Log lines and the
output of its child processes stay off the screen, and the log file still
receives every record.

## Screens and keys

Press `1`, `2`, or `3`, or click its name in the top line, to show a
screen. Keys `4` to `6` do nothing.

| Key | Screen | Purpose |
| --- | --- | --- |
| `1` | Record | Record microphone and system audio, and view the transcript. |
| `2` | Library | Review saved sessions, and transcribe audio files. |
| `3` | Settings | Edit settings on one page, and run the system checks. |

Each screen has one top line and one row of key hints at the bottom. Long Settings values are cut with `…`. The hint row
starts with `? help · q quit` and lists the other keys in order of importance. When the row
is too narrow, whole items drop from the right; `? help` always stays. Press `?` to open a help overlay that lists every
key of the current screen; press `?` or `escape` to close it. Each control on
screen prints its key, for example `[r] Run again`, and a click on it does the
same as the key.

| Key | Action |
| --- | --- |
| `?` | Open the help overlay of the current screen; `?` or `escape` closes it. |
| `q` / `ctrl+c` | Quit. The hub asks first while a recording runs or still saves, while a file job runs, and while Settings has unsaved changes. |

While a text input has focus, such as the Library search or a Settings row,
letters, `?`, and `q` go to the input. The hint row then shows only the keys
that still act, for example `enter keep · esc cancel`.

The top line shows, from left to right:

- **Navigation:** `1 Record`, `2 Library`, and `3 Settings`. The current screen
  has a bold `▶` marker. Record shows `● HH:MM:SS` while a recording runs and
  `Ⅱ HH:MM:SS` while it is paused. Library shows its entry count. Settings
  shows `NW` when the last check run has warnings and `NF` when it has
  failures.
- **Engine status:** the model (`bark-pro-int8`), the state, the CPU use of the
  hub and its speech worker (`cpu`), and the memory of the hub and its worker
  (`ram`). For example: `bark-pro-int8   ready   cpu  12%  ram  1.2G`. The state is
  `ready` (a recording runs), `idle 212s` (the model is in memory and unloads in
  212 seconds), `idle` (the model is not in memory), `transcribing 43%` (a file
  job runs), or `labelling` (a stopped recording gets its speaker labels). The
  values update once per second. A value shows `—` before its first sample.

Each changing value has a slot of fixed width, so a new value does not move
the text beside it. Numbers are right-aligned in their slots.

### Sizes

The hub works in any terminal from 60 columns by 16 rows. It has three size
tiers by terminal width:

| Tier | Columns | Changes |
| --- | --- | --- |
| Wide | 120 and more | Every value shows. |
| Medium | 80 to 119 | The Library table drops the `kind`, `size`, and `state` columns and shows a state glyph. The Checks list shows the check names only. |
| Narrow | 60 to 79 | The top line shows only `●` or `Ⅱ` for a recording, no Library count, and the first word of the engine state. The Record speaker row and the speaker row of an open Library session are one line. The Library table also drops `speakers`, and the open session shows no Play position. Checks shows the list alone and only the counts on the tab line. |

The top of Record depends on the width and the height, so the transcript keeps
its space in a short terminal:

| Form | Size | Top of Record |
| --- | --- | --- |
| Full | 120 columns and 28 rows or more | REC panel and full spectra |
| Short spectrum | 80 columns and 20 rows or more, when the full form does not apply | one status line and two short spectra |
| Level line | every other size from 60×16 | one status line and one level line per source |

The top line is one line at every size. When it is too narrow, the model name
drops first, then `ram`, then `cpu`; the navigation and the engine state stay.
A dialog is never wider than the terminal width minus 4 columns.

Below 60 columns or 16 rows, the hub shows only one centred line, for example
`60×16 needed · now 52×14`. A recording continues, and the screen comes back
when the terminal is large enough again.

Scrollbars stay visible. Their thin accent-colour thumbs are the only exception
to the no-background rule; tracks and corners stay transparent.

## Hub lifecycle

Record is idle when the hub opens. Press `space` to start recording; while a
session is active, `space` pauses or resumes it. Recording continues when you
change screens. The hub runs recording start, stop, and save work in the
background so the interface can remain responsive.

Press `q` or `ctrl+c` to quit. When work is active, the hub asks one question
that lists each action: stop and save the recording, finish saving the stopped
recordings, and cancel the running file job. Press `y`, `q`, or `ctrl+c` (or click the
confirm button) to run the actions in order and quit; press `n` or `escape` (or
click the cancel button) to keep working. If a recording cannot save or the
file job cannot cancel, a notice shows the error and the hub stays open. A
cancelled file job does not leave a partial output file. If a start, stop, or
save operation is still in progress, wait for its status to finish before you
send another quit key.

If Settings has unsaved changes, the hub asks whether to save, discard, or stay
before it leaves Settings or quits. A tab change inside Settings keeps the
changes and does not ask. A successful save keeps a timestamped
`config.toml.bak-<time>` backup and preserves comments and settings that the
editor does not know about.

## Record

Record has a REC panel, a MIC meter, and a SYSTEM meter at the top. Below them,
a speaker bar sits above the full-width transcript. The transcript gets the
space first. In the short-spectrum and level-line forms, the REC panel is one
status line: the state, the clock, one note (the microphone, `started HH:MM`,
`saved HH:MM`, or the error; not in the narrow tier), and two buttons. Each
button keeps the width of its widest label, so a label change moves nothing.
The session ID shows only in the full form, and the narrow tier uses short
button labels such as `[enter] ■ Stop` and `[space] ● Record`. In the status
line, `[d] device…` is the second button while no recording runs. Capture is local: Record never sends audio over
the network. When Refine is on, a saved recording sends samples of its
transcript to the Refine host for a [title](#titles). Each state shows a glyph and a word, so it does not
depend on colour.

| State | REC panel | Keys |
| --- | --- | --- |
| Idle | `○ READY`, the microphone device, `[space] ● Record` | `space` record · `d` device · `m` mic · `s` system · `v` view |
| Recording | `● REC`, the elapsed clock, `started HH:MM`, `[enter] ■ Stop & save`, `[space] Ⅱ Pause` | `enter` stop & save · `space` pause · `m` mic · `s` system · `v` view · `r` rename |
| Paused | `Ⅱ PAUSED` and `[space] ▶ Resume` | as Recording, with `space` resume |
| Saved | `■ SAVED`, the final duration, `saved HH:MM`, the session ID, `[space] ● Record again`, `[o] Open in Library` | `space` record again · `o` open in Library · `d` device · `m` mic · `s` system · `v` view · `r` rename |
| Save failed | `! SAVE FAILED`, the error, the session ID, `[space] ● Record again`, `[o] Open in Library` | as Saved, without `r` rename |

| Key | Action |
| --- | --- |
| `space` | Start a recording; during a recording, pause or resume it. |
| `enter` | Stop and save the recording. |
| `o` | Show the saved session in Library. |
| `d` | Choose the input device for the next recordings, while no recording runs. |
| `m` / `s` | Turn the microphone or system audio on or off. |
| `v` | Switch between the mixed and split transcript views. |
| `r` | Rename a speaker. |
| `up` / `down`, `pageup` / `pagedown`, `home` / `end` | Scroll the transcript. |

Press `enter` (or click `[enter] ■ Stop & save`) to stop and save. The hub
stays open and the save runs in the background: the transcript title shows
`saving…` until it ends. The session keeps the speaker labels shown during the
recording; a stop runs no speaker pass, so it takes seconds. While it saves, the
saved session is busy: `rename busy` shows in the speaker bar, `[r] Rename…` is
disabled, and `r` shows the notice `session busy`. You can press `space` to
record again while it saves. When the save ends, the
transcript ends with a marker line such as
`── saved · 31 phrases · mic.flac 88 MB · system.flac 0.2 MB ──` (only the
audio files that exist). Press `o` to show the session in Library. If the save
fails, also for an older session that was still saving, a notice shows the error
and the REC panel shows `! SAVE FAILED` with that session until the next recording
starts; `o` still shows what the session folder holds. If several saves fail, the
panel lists each error and session, and each press of `o` shows the next session.

If you quit while a session still saves, the quit question lists it. Press `y`
to quit after each session has saved; press `n` to keep the hub open.

In the full form, each meter shows 18 frequency bands in 8 rows, the band labels
`100 200 400 800 1k6 3k2 6k4`, the level and the 3-second peak in dBFS (for
example `-23.4`), and a speech light (`● speech` or `○ quiet`) from the voice
detector of the source. In the short-spectrum form, the meters sit side by side with
2 rows of bands and no band labels; the microphone head leaves `[d] device` to the
status line, so the device name still shows at 80 columns. In the level-line form, each source is one line:
`[m] MIC` or `[s] SYS`, a level bar from -60 to 0 dBFS, the level, and the
speech light.
While no recording runs, a meter shows a dotted grid and `not recording`.
Press `m` or `s` to turn a source on or off. During a recording, the key
changes the running session. Before a recording, the key chooses the sources
of the next recording; a source that is off shows `off · press m to enable` (or
`s`). System audio captures the current output mix, not separate applications.

Press `d` (or click `[d] change device…`) while no recording runs to choose the
input device. The dialog lists each PipeWire microphone by its description, and
`Settings default`. A
chosen device that is gone shows as `unavailable` and stays selected until you
choose another row. The choice shows in the MIC meter and applies to the next
recordings until the hub quits. It does not change `config.toml`; the Microphone row
of Settings edits the saved device.

The transcript opens in mixed view, with one time-ordered stream and speaker
labels. Press `v` (or click `[v] ▶ mixed  split`) to switch to split view,
where microphone and system lines appear in separate, captioned columns in time
order. The row of scroll keys under the transcript is hidden in the narrow tier and in the
level-line form. Use `up` and `down` to scroll one line, `pageup` and `pagedown` to scroll
one page, and `home` and `end` to move to the top and bottom. The mouse wheel
also scrolls the transcript. New lines stay in view while the transcript is at
the bottom. If you scroll up, refreshes do not move the view; press `end` or
scroll to the bottom to follow new lines again.

The speaker bar lists each speaker that has transcript lines, with its talk time
(`4:12`; from 100 minutes, `1h40m`).
The speakers take one line in the narrow tier and in a terminal of fewer than 28
rows, and at most two lines in other sizes; they wrap between speakers, and the
last line ends with `+N` for the speakers that do not fit. The notices wrap
below the speakers. Each speaker shows as
text, so it does not depend on colour. The end of the bar shows the count of failed
phrases when there are any, `! mic stopped` (or `! system stopped`) when the capture of
a source failed, `! mic no audio` (or `! system no audio`) while a
running source has delivered no audio for 5 seconds, `! mic audio not saved` when a source's audio
cannot be written, and a notice when lines get no speaker label (see
[Speaker labels](#speaker-labels)). `[r] Rename…` sits in the transcript title row. After such a failure the source keeps
transcribing, its audio file ends at the failure, and the recording still saves
its transcript. Press `r` (or click `[r] Rename…`) to open the Rename speaker dialog:
choose the speaker, type the new name, and press `enter` (or click `[enter] Rename`); `escape` cancels. During a recording, the
rename changes the live labels. On a saved session, the rename writes a new
transcript revision of that session.

Both sources record through a `pw-record` child process. A source that delivers
no audio for 5 seconds while it runs shows `! mic no audio` or
`! system no audio`, and the log gets one `live: source_silent` warning. Nothing
restarts: the line goes away when audio arrives again. When the capture process
of a source exits or cannot start, for example because a named microphone is
unplugged or absent, that source turns off, Record shows `! mic stopped` or
`! system stopped`, the log gets `live: mic_source_failed` or
`live: system_source_failed`, and the other source keeps recording. Nothing
restarts. The line shows exactly while the source is off because its capture
failed and you have not pressed its key (`m` or `s`) since; stopping the
recording clears it. A sample that `pw-record` delivers as NaN or infinity
becomes silence (0.0), so the audio file keeps recording; when such a capture
ends, the log gets one `capture: non_finite_samples_replaced` warning with the
source and the count. Dictation reads the microphone the same way.

### Prepare the models

Record uses the same speech model as dictation and file jobs: Underdog Bark 3.0
Pro, int8 ONNX on the CPU. Build it once when you choose to:

```sh
stenographer model download --asr
```

It needs `python3-venv`, 10 GiB of free disk, and about 10.2 GiB of RAM; see
[build the speech model](usage.md#build-the-speech-model). Record also uses the
Silero voice-activity model and the speaker model, NVIDIA Nemotron-3-Diarization,
run by NeMo-Speech.cpp. Both ship with the app, so there is nothing else to
download. Speaker labels need an x86-64 CPU with AVX2 or an ARM64 CPU.

### Separate the speakers in a room

When several people share one microphone, turn on microphone diarization:
set `live.diarize_mic` (default `false`) with the Separate room speakers row of Settings. A new
recording then labels microphone speakers `Room 1`, `Room 2`, and so on
(speaker IDs `room-1`, `room-2`), apart from the system speakers (`Speaker 1`,
...). Microphone and system audio are separate speaker streams, so a room
voice and a system voice never share a label. `r` lists room speakers with the
system speakers. The setting applies when a recording starts; Record has no
toggle for it. With the setting off, microphone lines are `You`.

Limits:

- Room labels are estimates. They can split one person or merge several people.
- System audio that leaks into the microphone can appear as a room speaker. Use
  headphones to avoid this.

### System capture limits

System capture records the full mix from the current default output sink. It
does not capture separate applications. It requires PipeWire, `pw-record`, and
`pactl`. A recording does not follow a change to the default output sink. If
you do not need system audio, press `s` to turn it off.

Echo cancellation is out of scope. System audio can also reach the microphone
and appear twice. Use headphones, or press `m` to turn off the microphone.

Each phrase is decoded on the CPU. Microphone and system phrases share one
processing queue, so a backlog can delay lines. Running `stenographer run` and
the hub together is supported. Each loads its own copy of the speech model,
and both can compete for CPU time.

### Speaker labels

A line ends at a pause or where the speaker changes, and has one speaker.
Nemotron-3-Diarization finds the speaker changes; each line is decoded once.
A part of a line that decodes to no text joins the part before it (or its only
neighbour) and is decoded once more, so its speech stays in a line.
During a recording, a line shows a few seconds after its last word, when its
speakers are final. Speakers are numbered from 1 in order of first appearance,
per source: `Speaker N` for system audio, `Room N` for the microphone with
`live.diarize_mic` on. Labels are estimates, not identity checks.

Lines get no speaker label (`You` for the microphone, `System` for system audio)
when the CPU cannot run the speaker model, or the speaker process does not start
or stops. Settings > Checks shows the reason in the `speaker labels` row. If the
speaker process falls a minute behind the audio of a source, that source shows
`! system speakers behind` (or `mic`) in the speaker bar and its new lines get no
speaker label; when you stop, stenographer labels that source again from its
saved audio, and the speaker bar's notice is the only sign before then.

### Saved session files and privacy

Sessions are saved under
`$XDG_DATA_HOME/stenographer/sessions/<UTC YYYYMMDDTHHMMSSZ>/`. If
`XDG_DATA_HOME` is not set, the directory is
`~/.local/share/stenographer/sessions/<UTC YYYYMMDDTHHMMSSZ>/`.

The session directory has mode `0700`. Each file has mode `0600`. Files are
created only for sources that were active during the session:

- `mic.flac` and `system.flac` contain 16 kHz, mono, FLAC `PCM_24` audio.
  Audio is flushed as the session runs. A source that is off during part of
  the session has silence for that time in its file.
- `transcript.jsonl` contains one JSON object per recognized phrase. Each
  object has `start`, `end`, `wall` (UTC), `source`, `speaker_id`, `label`, and
  `text` fields. Speaker rename events are also recorded.
- `transcript.md` is written when the session stops. It contains the saved
  transcript and the final display labels.
- `session.json` records the current transcript revision. A session recorded
  with microphone diarization has it from the start, with `"diarize_mic": true`.

These files are user data that you request when you record. The hub recording writes audio and transcripts to the session folder. A requested
export writes a transcript to the selected folder. When Refine is on, the hub
sends samples of a saved transcript to the Refine host for a
[title](#titles). Logs and analytics do not contain transcript text, titles, or
audio. See the [privacy
notes](usage.md#understand-privacy-and-network-access) for other Stenographer
network behavior.

## Library

Library is one table of saved recordings, file sessions, and file jobs that are
not finished, newest first. Each entry is two lines tall. Press `enter` to open
the selected entry on the full screen; press `escape` to return to the table
with the same entry selected. The table scrolls to keep the selected entry in
view.

The columns depend on the [size tier](#sizes):

- **Wide:** `date`, `dur`, `kind` (`rec` or `file`), `speakers`, `title`,
  `size`, and `state`.
- **Medium:** `date`, `dur`, `speakers`, `title`, and a state glyph.
- **Narrow:** `date`, `dur`, `title`, and a state glyph.

The `speakers` cell lists the speaker names, most talk time first, on up to two
lines; `+N` counts the names that do not fit. The `title` cell wraps to the
second line, and a longer title ends with `…`. A recording without a title shows
`—`; in the narrow tier it shows its speaker names, dimmed. A file session or a
file job without a title shows the name of its file.

The `state` cell of the wide tier shows a word: the label state (`live`,
`relabeled`, or a revision method such as `rename` or `re-transcribe`; a
revision that a file job wrote also shows `re-transcribe`),
`! interrupted` when the recording stopped without a clean save, `× failed` for
a failed file job, or the work that changes the entry. A file job shows
`transcribe`; a file job that writes a new revision of a listed session shows
`re-transcribe` on that session row. Work that the Library starts on a session
shows its name while it runs: `re-diarize`, `re-transcribe`, `rename`, `title`,
or `delete`. The open session shows the same word. The medium and narrow tiers
show only a glyph: `!` interrupted, `×` failed.

Only file jobs, which [Transcribe a file](#transcribe-a-file) queues, show
`queued` or their percent in the `dur` cell, and only they can be cancelled.
This includes a file job on the `mic.flac`, `system.flac`, or `source.<ext>` of
a listed session. `d`, `t`, a rename, a title, and a delete show no percent and
cannot be cancelled. A failed file job shows `× failed`; press `delete` to
remove its row. When a file job finishes, its row becomes the session row and
stays selected.

The table updates when a job ends and when a recording is saved, and it keeps
the selected entry. The active recording does not appear until it is saved.
The line above the table shows the entry count and the audio size; the top line
shows the entry count.

Press `/` to search titles, session IDs, start times, file names, and
transcripts; the search ignores case and runs in the background. Recording
times include the local date and time shown in the table and the UTC timestamp.
A job row matches by its source file name. Press `escape` to clear the search.

The open session shows its state, date, duration, kind, and size, the title,
each speaker's talk time, the action buttons, and the transcript. While a player
runs, the Play button shows `■ Stop` and the position in the session, for
example `■ Stop 00:04:12 / 00:30:00`; the narrow tier shows no position. Buttons
that do not fit the width hide; their keys still act. The action keys act on
the selected entry in the table and in the open session:

| Key | Action |
| --- | --- |
| `n` | Open the [Transcribe a file](#transcribe-a-file) dialog. |
| `enter` | Open the selected entry on the full screen. |
| `escape` | Return to the table; in the table, clear the search. |
| `up` / `down` | Select the previous or next entry; in an open session, scroll the transcript one line. |
| `/` | Search titles and transcripts. |
| `p` | Play or stop the session audio with `pw-play`. A file session plays its source file. On another session, `p` stops the audio that plays and starts that session. A notice shows when the player exits with an error. |
| `e` | Edit the title of the session. An empty title removes the title. |
| `g` | Generate a title with the Refine model. See [Titles](#titles). |
| `r` | Rename a speaker of the session. Speakers that share a name are one row, and all of them get the new name. |
| `d` | Re-diarize the session. This also needs the speech model. A file session cannot: use Re-transcribe. A recording without separated speakers (no system lines, and mic lines recorded as `You`) cannot either. |
| `t` | Re-transcribe the session. A source with speaker separation also gets its speakers again, so labels can change. |
| `x` | Export the transcript. |
| `delete` | Delete the session after confirmation; this also stops its audio when it plays. On a queued or running file job, cancel the job after confirmation. |
| `pageup` / `pagedown`, `home` / `end` | Move the selection one page, or to the first or last entry; in an open session, scroll the transcript. |

### Titles

The title row of the open session has `[e] Edit title…` and
`[g] Generate title`; the narrow tier shows only `[e] Title…`, and `g` still
acts. `g` asks the configured Refine model (`refine.host` and `refine.model`)
for a one-line title. Before it replaces a title that you typed, it asks for
confirmation: press `y` to generate or `n` to keep the title. While the model
works, the title shows a dimmed `generating…` in the table and in the open
session, and `e` and `g` on that session show `session busy`; the other keys act
as before. A session without transcript lines gets no request. A failure shows a
notice, and the title stays as it was.

When Refine is on (`refine.enabled`) and its model is installed on the Refine
host, each recording that the hub saves and each file job that finishes in the
hub gets a title automatically, one request at a time in the background. An
automatic title never replaces a title, and a failure leaves the session
without a title and writes one warning to the log. Older sessions and sessions
from `stenographer transcribe` get a title only from `g`.

The request sends the whole transcript, or for a transcript of more than 1800
words three samples of about 600 words from its start, middle, and end, with the
speaker names. It goes only to the Refine host, which is loopback by default; a
host that is not loopback receives these samples over the network. The reply
must be one line of at most 80 characters, or it is discarded.

The title is stored in the `session.json` of the session as `title`, with
`title_source` `user` for a title that you typed and `model` for a generated
title. Like the transcript, the title stays in the session folder; the hub does
not write it to logs, history, or analytics. A session without a title loads as
before.

For delete and job cancellation confirmations, press `y` to confirm or `n`
to keep the session or job. `q` and `ctrl+c` do not confirm these prompts.

While a re-diarize, re-transcribe, rename, title, delete, or file job changes a
session, that session is busy: its Edit title, Generate title, Rename, Re-diarize,
Re-transcribe, and Delete buttons are dimmed, and their keys show the notice
`session busy`. Play and Export still act. While the model generates a title,
only Edit title and Generate title are dimmed. While a file job writes a new
revision of the session, its Delete button is `Cancel job…` and `delete`
cancels that file job. During `d`, `t`, a rename, a title, or a delete, the
Delete button is dimmed and `delete` shows `session busy`.

`x` opens the Export dialog. Press `tab` or click a format to choose `md`,
`jsonl`, `srt`, or `txt`, and type the folder (default `~/Documents`). Press
`enter` to export or `escape` to cancel. The notice shows the path of the
exported file. If export fails, the dialog keeps the folder and format so you can retry.

Re-diarization and re-transcription write new transcript revisions and keep
previous revisions. If an existing `session.json` is unreadable or invalid,
the revision fails to preserve its metadata. Older sessions without that file
can still be revised. Both use the [speaker label rule](#speaker-labels) on the
saved audio of each source with speaker separation: a line where the speaker
changes is cut there and each part is decoded again. Re-diarization labels
microphone lines as `Room N` speakers only for a session recorded with
microphone diarization (`"diarize_mic": true` in its `session.json`). For
other sessions, including older ones, it labels system lines only and
microphone lines stay `You`. A new speaker keeps the name you gave to most of
its time. Saved sessions keep their labels until you press `d` or `t`.

Re-diarize fails when speaker labels cannot run on this computer; Re-transcribe
then keeps the speakers and replaces only the text. A file imported without
Separate speakers keeps its one speaker. A file imported before this record
existed counts as separated when it has two speakers or its speaker pass failed.

### Transcribe a file

Press `n` or click `[n] + Transcribe a file…` to open the Transcribe a file
dialog. It has a file browser and the job options:

- The browser starts in your home folder. It lists `..`, the folders, and the
  supported audio files of the current folder, with durations when soundfile can determine them. Hidden folders are listed; search with a leading dot to show hidden audio files. If a folder cannot be read, the browser shows the reason and retains `..` for navigation. Press `up` and `down` (or click a row) to select
  an entry. Press `enter` on a folder to open it. Press `/` to search names in
  the current folder; `escape` clears the search.
- **Separate speakers** (`s`): identify and label speakers; a line also ends
  where the speaker changes. On by default.
- **Refine text** (`r`): apply the configured text-refinement service. Off by
  default.

Press `enter` on a file (or click `[enter] Transcribe`) to queue one job with
these options; `escape` clears an open search first and otherwise closes the dialog.
Click `[esc] Cancel` to close the dialog.
If a job fails after producing lines, its failure appears above those lines. The Library shows the job at once and selects it: a new file row, or the
session row for a revision job. Jobs run one at a time in the background. The
dialog has no output format or output folder option.

The browser lists WAV, FLAC, OGG, MP3, Opus, AAC, M4A, MP4, MKV, WebM, and WMA
files. Files that `soundfile` can read use that library. M4A and AAC files use
the system `ffmpeg` executable; other files that `soundfile` cannot read also
use `ffmpeg`. Stenographer does not bundle FFmpeg. Install it with your system
package manager. The Checks tab reports when `ffmpeg` is missing; a job that
needs it fails with `× needs ffmpeg` in the open entry of the Library.
`stenographer transcribe FILE` decodes with the same code. Where `ffmpeg` is missing and the
file needs it, the command prints `needs ffmpeg` and exits with status 69. A file that
`soundfile` cannot read, such as a damaged WAV file, needs `ffmpeg` too, so without `ffmpeg`
it also gives `needs ffmpeg` and status 69. A missing file, or a file that `ffmpeg` cannot
read, exits with status 2.

Each job saves its result in the sessions folder, next to your recordings
(`$XDG_DATA_HOME/stenographer/sessions/`, or
`~/.local/share/stenographer/sessions/` when `XDG_DATA_HOME` is unset):

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
  (mic) or `Speaker 1` (system); when speakers are not separated, mic lines
  are `You` and system lines `System`. Earlier renames of the replaced source do not carry over.
- **`source.<ext>` of a file session:** the job saves a new transcript
  revision that replaces all lines.

A path outside the sessions folder, a symlink that leads out of it, or a file in
a subfolder of a session makes a new session. A cancelled or failed job
removes the folder that it made, and a revision job that stops leaves the
session unchanged. When the session changes while a revision job runs (for
example, a speaker rename), the job fails and keeps the newer revision.
Earlier results in the old `files/` folder stay where they are; the hub does
not read, move, or delete them.

## Settings

Settings has two tabs: Settings and Checks. Press `left` and `right`, or click
a tab, to change the tab. A `▶` marks the active tab. The Settings tab is one
page that edits `config.toml` in six groups:

| Group | Settings |
| --- | --- |
| Keys | Agent key, General key, Cancel key, Hotkey mode |
| Audio | Microphone, Volume, Sound pack, Overlay |
| Text | Vocabulary, Copy original, Restore clipboard |
| Refine | Refine, Host, Model |
| Recording | Separate room speakers, Meter floor dBFS |
| System | Usage history, Idle unload |

A terminal of 120 columns or more shows the groups in two columns. A narrower
terminal shows one column that scrolls; below 80 columns it has no empty line
between groups.

Each row shows a `●` slot, the setting name, and its control. See the
[settings reference](#settings-reference) for what each setting does. A `▶`
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
default. The tab row holds `[u] Undo`, `[D] Reset row`, `Discard all`, and
`[ctrl+s] Save`; Discard all asks first. In a terminal of 120 columns or more,
`N changes` follows Save. In a narrow terminal, Reset row and then Undo leave
the tab row; their keys still act.

The line under the tabs is the message line: `config.toml · ● N unsaved
changes · <message>`. The message is one of these:

- `× <setting> <reason>` while the config refuses a value, for example
  `× Model must be non-empty`. The input stays open.
- `default <value>` when the value of the selected row differs from its default.
- The newest `config.toml.bak-<time>` backup and its time.

Below 80 columns the line has no `config.toml · ` prefix. Click a row to
select it, and click it again to edit it. Idle unload is the one shared ASR
setting for dictation, Record, and file jobs. Model downloads are explicit. Run
`stenographer model download --asr` to build the speech model; see
[build the speech model](usage.md#build-the-speech-model).

The Vocabulary row (`refine.vocabulary`) opens a list editor. Press `a` to
add a term, `e` to edit the selected term, and `del` to delete it. In the
term input, `enter` keeps the term and `escape` closes the input. A term is
trimmed, is not empty, has at most 64 characters, and does not repeat another
term in any letter case; the list holds at most 200 terms. The editor refuses
a term that breaks a rule: the input stays open and the line under it names the
rule, for example `× term not kept: term 3 must be non-empty`. `enter` Done makes the list an
unsaved change of Settings; `escape` cancels.

| Key | Action |
| --- | --- |
| `left` / `right` | Select a tab. |
| `up` / `down` | Select a setting. |
| `enter` | Edit the selected setting. |
| `space` | Flip the selected toggle. |
| `u` | Undo the last edit. |
| `shift+d` | Reset the selected setting to its default. |
| `/` | Search setting names; `escape` clears the search. |
| `ctrl+s` | Save changes and keep a timestamped backup. |

Settings apply to new sessions and jobs. Work that is already running keeps
its current settings.

### Settings reference

| Setting | Key | What it does |
| --- | --- | --- |
| Agent key | `hotkey.binding` | The dictation binding for agent-directed dictation and its cleanup. |
| Cancel key | `hotkey.cancel_binding` | The global cancel key of dictation. Blank disables it. |
| Hotkey mode | `hotkey.mode` | The hotkey behavior: hold, toggle, or hybrid. |
| General key | `hotkey.general_binding` | The dictation binding for ordinary transcript cleanup. |
| Volume | `feedback.volume` | The playback volume of dictation feedback sounds. `0` is silent. |
| Overlay | `feedback.overlay` | Shows the best-effort status overlay of dictation. |
| Sound pack | `feedback.sound_pack` | The name of the feedback sound pack. |
| Copy original | `delivery.copy_original` | For the Agent key, and only when cleanup changed the text, copies the original transcript too. |
| Restore clipboard | `delivery.restore_clipboard` | Restores the previous clipboard item after dictation delivers its text. |
| Usage history | `analytics.enabled` | Stores local numeric usage history of dictation and `stenographer transcribe`, with local resource use during utterances. No audio or transcript text is stored. |
| Microphone | `audio.input_device` | The PipeWire source name for dictation and Record; the picker lists each microphone by its description. Blank, `pipewire`, `default`, `pulse`, or a number uses the default microphone. Record's `d` key can choose another device for its next recording. |
| Meter floor dBFS | `feedback.spectrum_floor_dbfs` | The floor of the Record meters and the dictation overlay in dBFS: one fixed value, or one value per band. |
| Idle unload | `asr.idle_unload_seconds` | The seconds before the idle speech worker unloads, and how long Ollama keeps the refine model loaded when idle. Zero never unloads either one. |
| Vocabulary | `refine.vocabulary` | Terms that refine spells exactly as written. |
| Refine | `refine.enabled` | Runs text cleanup after each dictated utterance. File jobs and `stenographer transcribe --refine` choose it per run. When it is on, the hub also asks the refine model for the [title](#titles) of each saved recording and finished file job. |
| Host | `refine.host` | The Ollama server of refine and of titles. A host that is not loopback receives transcript text. |
| Model | `refine.model` | The model name on the refine service. |
| Separate room speakers | `live.diarize_mic` | Separates the speakers on the microphone as Room 1, Room 2, and so on. Off labels every microphone line You. It applies to new Record recordings. |

### Checks

The Checks tab runs the system checks the first time it opens, in the
background, so the hub keeps answering keys while they run. It merges the
former Doctor and Setup sections. The checks are grouped:

| Group | Checks |
| --- | --- |
| input | input access, microphone, input device, hotkey, sounds |
| engine | speech model, refine service, system audio, system service |
| other | each other doctor check, such as ffmpeg, the clipboard, and the overlay |

Each row shows a state glyph, the check name, and a short detail that is cut
to fit: `✓` pass, `!` warning, `×` failure. In the medium tier the list shows
the check names only. In the narrow tier the tab shows the list alone: press
`enter` to show the detail of the selected check and `escape` to return to the
list; the detail puts `[esc] ← Checks` in place of the tab names. The detail pane shows the
selected check with its state word, the result, fix guidance when available,
`checked HH:MM` and the related path when one applies, and the buttons
`[f] Fix: …` (for a warning or failure that has a fix), `[t] Test: …` (when
the area has a test), `[l] Open log`, and `[c] Copy report`. The detail scrolls when it does not fit;
`[Q] Quick setup…`, `[m] Models…`, and `[D] Defaults…` stay at its bottom. A row of
buttons that does not fit on one line shows one button on each line.

Checks has no frame of its own inside the Settings frame; in the wide and medium
tiers one vertical line divides the list from the detail. The tab line shows,
after the tab names, `N pass · N warn · N fail`, the time of the last run, and
`[r] Run again`. In the medium tier `[r] Run again` shows only when it fits
whole, and the time shows only when it fits whole; the narrow tier shows the
counts only (`r` still runs the checks). The Settings navigation badge shows `NW` for warnings or `NF` for
failures, and the tab label shows `●N` when the last run has warnings or
failures. New optional checks appear as warnings and do not change the
existing `stenographer doctor` exit status. The refine service check asks the
configured Ollama host for its model list only while refine is on; it sends
no transcript text.

| Key | Action |
| --- | --- |
| `up` / `down` | Select a check. |
| `enter` | Narrow tier: show the detail of the selected check. |
| `escape` | Narrow tier: return from the detail to the list. |
| `r` | Run the checks again. |
| `f` | Fix: select the related Settings row, or open the Quick setup or Models dialog. |
| `t` | Test the area of the selected check. |
| `l` | Open the log. |
| `c` | Copy the check report. |
| `shift+q` | Open Quick setup. |
| `m` | Open Models. |
| `shift+d` | Open Defaults. |

A test result stays with its check, including while it is running. Defaults warns before discarding unsaved settings. Unreadable warning logs are identified in Checks and the copied report.

The microphone test lists the PipeWire microphones and does not capture audio.
The microphone check fails when `pw-record` or `pactl` is missing or no
microphone is found. The input device check warns when `audio.input_device` is
a number from an older version; pick the microphone again. The
sound test plays the preview of the sound pack. The hub does not start or
restart the system service.

Recent warnings, under `recent warnings`, show only the
time, the level, the event token, such as `live: system_source_failed`, and a
fixed description for known tokens. They never show a log message, exception
text, or a field of the log line. The copied report uses the same form.

The dialogs:

- **Quick setup** shows input access, microphone, and hotkey with their state
  and current value. Press `t` to test the selected step and `e` to open its
  setting.
- **Models** shows the speech model with its size, as present or missing.
  Press `enter` on a missing model to build it. One download runs at a time; a
  notice shows when another one is running.
- **Defaults** writes the default configuration after a confirmation and
  keeps the current file as a timestamped backup.

The `stenographer setup` and `stenographer doctor` commands do not change.

The Record meters use the saved spectrum floor for each new recording. Returning
to a saved recording refreshes its transcript; deleting that session clears Record.
Library shows search progress and read errors, including alongside file jobs.
Speaker rename waits for the session details to load. File transcription requires
a valid configuration before the dialog opens. Switching Settings tabs keeps a valid
inline edit and stays on the current tab if the value is invalid. Model status
refreshes when the dialog opens and before or after a download.
