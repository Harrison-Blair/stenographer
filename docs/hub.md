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
| `3` | Settings | Edit settings by tab, and run the system checks. |

Each screen has one top line and one row of key hints at the bottom. Long Settings values wrap. The hint row
starts with `? help · q quit`. Press `?` to open a help overlay that lists every
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
  shows `N W` when the last check run has warnings and `N F` when it has
  failures.
- **Engine status:** the model (`bark-pro-int8`), a state such as
  `ready · 2 queued` or `idle · unloaded`, the CPU use of the hub and its speech
  worker (`cpu`), the CPU use of the system (`all`), and the memory of the hub
  and its worker (`ram`). For example:
  `bark-pro-int8 ready  cpu 12% all 40%  ram 1.2G`. The values update once per
  second. A value shows `—` before its first sample.

The screens need at least 120 columns.

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
a speaker bar sits above the full-width transcript. Capture is local: Record never sends audio or
transcript text over the network. Each state shows a glyph and a word, so it does not
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

Each meter shows 18 frequency bands in 8 rows, the band labels
`100 200 400 800 1k6 3k2 6k4`, the level and the 3-second peak in dBFS, and a
speech light (`● speech` or `○ quiet`) from the voice detector of the source.
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
recordings until the hub quits. It does not change `config.toml`; the Audio tab
of Settings edits the saved device.

The transcript opens in mixed view, with one time-ordered stream and speaker
labels. Press `v` (or click `[v] ▶ mixed  split`) to switch to split view,
where microphone and system lines appear in separate, captioned columns in time
order. Use `up` and `down` to scroll one line, `pageup` and `pagedown` to scroll
one page, and `home` and `end` to move to the top and bottom. The mouse wheel
also scrolls the transcript. New lines stay in view while the transcript is at
the bottom. If you scroll up, refreshes do not move the view; press `end` or
scroll to the bottom to follow new lines again.

The speaker bar lists each speaker that has transcript lines, with its talk time.
The row wraps between speakers when it runs out of room. Each speaker shows as
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
restarts: the line stays until the recording stops, or until you turn the source
on again (`m` or `s`) and its capture starts. A source that you turn off shows no
line.

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
set `live.diarize_mic` (default `false`) on the Live tab of Settings. A new
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
During a recording, a line shows about one second after its last word, when its
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
export writes a transcript to the selected folder. Logs and analytics do
not contain transcript text or audio. See the [privacy
notes](usage.md#understand-privacy-and-network-access) for other Stenographer
network behavior.

## Library

Library has a list of eight rows above the full-width detail of the selected
entry. The list scrolls to keep the selected row in view. It holds saved recordings, file sessions, and file jobs that are
not finished, newest first. Its columns are `date`, `dur`, `kind` (`rec` or
`file`), `spk` (speaker count), and `labels`:

- **Recording:** `labels` is `live` for the speaker labels shown during the
  recording, `relabeled` after a re-diarize or after a stop that labelled a
  source again from its saved audio, a revision method such as `rename` or
  `re-transcribe`, or `! interrupted` when the recording stopped without a
  clean save.
- **File session:** `labels` is the name of the source file. If the speaker pass
  of the job failed or could not run, the detail above the transcript shows `live labels`
  until a later revision, such as a rename or Re-transcribe.
- **File job:** `dur` shows `queued` or the percent done, and `labels` shows the
  source file name. A failed job shows `× failed`; press `delete` to remove its
  row. When a job finishes, its row becomes the session row and stays
  selected.
- **Revision job:** a job that writes a new revision of a listed session shows
  `queued` or its percent in the `dur` cell of that session row.

The list updates when a job ends and when a recording is saved, and it keeps
the selected entry. The active recording does not appear until it is saved.
The top edge of the list shows the entry count, the audio size, and the sessions
folder; the top line shows the entry count.

Press `/` to search session IDs, start times, file names, and transcripts; the
search ignores case and runs in the background. Recording times include the
local date and time shown in the list and the UTC timestamp. A job row matches
by its source file name. Press `escape` to clear the search.

The detail shows the date, time, duration, and kind, the label state, each
speaker's talk time, the microphone and system activity of a recording, and
the transcript. Each action is a button that prints its key:

| Key | Action |
| --- | --- |
| `n` | Open the [Transcribe a file](#transcribe-a-file) dialog. |
| `up` / `down` | Select the previous or next entry. |
| `/` | Search titles and transcripts. |
| `escape` | Clear the search. |
| `p` | Play or stop the session audio with `pw-play`. A file session plays its source file. On another session, `p` stops the audio that plays and starts that session. A notice shows when the player exits with an error. |
| `r` | Rename a speaker of the session. Speakers that share a name are one row, and all of them get the new name. |
| `d` | Re-diarize the session. This also needs the speech model. A file session cannot: use Re-transcribe. A recording without separated speakers (no system lines, and mic lines recorded as `You`) cannot either. |
| `t` | Re-transcribe the session. A source with speaker separation also gets its speakers again, so labels can change. |
| `x` | Export the transcript. |
| `delete` | Delete the session after confirmation. On a queued or running job, cancel it after confirmation. |
| `pageup` / `pagedown`, `home` / `end` | Scroll the transcript. |

For delete and job cancellation confirmations, press `y` to confirm or `n`
to keep the session or job. `q` and `ctrl+c` do not confirm these prompts.

While a re-diarize, re-transcribe, rename, delete, or file job changes a
session, that session is busy: its Rename, Re-diarize, Re-transcribe, and
Delete buttons show `busy` and do nothing, and a second change shows the
notice `session busy`. On a session row with a running revision job, `delete`
cancels the job.

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
needs it fails with `× needs ffmpeg` in the Library detail.

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

Settings has five tabs: General, Audio, Recognition, Live, and Checks. Press
`left` and `right`, or click a tab, to change the tab. A `▶` marks the active
tab. The first four tabs edit
`config.toml`:

| Tab | Settings |
| --- | --- |
| General | hotkey, sound and overlay feedback, log level, delivery, and analytics |
| Audio | input device, maximum recording length, and spectrum floor |
| Recognition | `asr.idle_unload_seconds`, `asr.cpu_threads`, and the refine settings |
| Live | `live.diarize_mic` |

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
`ctrl+s` keeps it and saves. When the config refuses a value, the input stays
open and the row shows `× <reason>`, for example
`× must be non-empty`.

A `●` marks a row whose value differs from the saved file, not from the
default. A row shows `default <value>` when its value differs from the default. The first row of the
panel shows the config file, `● N unsaved changes`, and the newest
`config.toml.bak-<time>` backup with its time. Below the rows, `[ctrl+s] Save N
changes`, `[u] Undo`, `[D] Reset row`, and `Discard all` act on the draft;
Discard all asks first. Click a row to select it, and click it again to edit
it. Recognition holds the one shared set of ASR settings for dictation,
Record, and file jobs. Model downloads are explicit. Run
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
| `/` | Search setting names in every tab; `escape` clears the search. |
| `ctrl+s` | Save changes and keep a timestamped backup. |

Settings apply to new sessions and jobs. Work that is already running keeps
its current settings.

### Settings reference

| Setting | Key | What it does |
| --- | --- | --- |
| Agent key | `hotkey.binding` | The dictation binding for agent-directed dictation and its cleanup. |
| Hotkey device | `hotkey.device` | The hotkey input device. Blank listens on the keyboards that stenographer detects. |
| Cancel key | `hotkey.cancel_binding` | The global cancel key of dictation. Blank disables it. |
| Hotkey mode | `hotkey.mode` | The hotkey behavior: hold, toggle, or hybrid. |
| Hold threshold | `hotkey.hybrid_threshold_seconds` | In hybrid mode, the press duration that separates a tap from a hold. |
| General key | `hotkey.general_binding` | The dictation binding for ordinary transcript cleanup. |
| Volume | `feedback.volume` | The playback volume of dictation feedback sounds. |
| Mute sounds | `feedback.mute` | Mutes dictation feedback sounds. |
| Overlay | `feedback.overlay` | Shows the best-effort status overlay of dictation. |
| Sound pack | `feedback.sound_pack` | The name of the feedback sound pack. |
| Log level | `feedback.log_level` | The minimum level of console log messages. |
| Copy original | `delivery.copy_original` | For the Agent key, and only when cleanup changed the text, copies the original transcript too. |
| Restore clipboard | `delivery.restore_clipboard` | Restores the previous clipboard item after dictation delivers its text. |
| Restore delay | `delivery.restore_delay_ms` | The wait, in milliseconds, before the clipboard is restored. |
| Usage history | `analytics.enabled` | Stores local numeric usage history of dictation and `stenographer transcribe`. No audio or transcript text is stored. |
| Resource profiling | `analytics.resource_profiling` | With Usage history on, measures local resource use during utterances. |
| Microphone | `audio.input_device` | The PipeWire source name for dictation and Record; the picker lists each microphone by its description. Blank, `pipewire`, `default`, `pulse`, or a number uses the default microphone. Record's `d` key can choose another device for its next recording. |
| Longest recording | `audio.max_recording_seconds` | The maximum length of one hotkey dictation. It does not limit Record. |
| Meter floor dBFS | `feedback.spectrum_floor_dbfs` | The floor of the Record meters and the dictation overlay in dBFS: one fixed value, or one value per band. |
| Idle unload | `asr.idle_unload_seconds` | The seconds before the idle speech worker unloads, and how long Ollama keeps the refine model loaded when idle. Zero never unloads either one. |
| CPU threads | `asr.cpu_threads` | The CPU threads of the speech worker. Zero is automatic. |
| Vocabulary | `refine.vocabulary` | Terms that refine spells exactly as written. |
| Refine | `refine.enabled` | Runs text cleanup after each dictated utterance. File jobs and `stenographer transcribe --refine` choose it per run. Record does not use refine. |
| Host | `refine.host` | The Ollama server of refine. A host that is not loopback receives transcript text. |
| Model | `refine.model` | The model name on the refine service. |
| Minimum words | `refine.min_words` | Shorter utterances skip refine. |
| Structured output | `refine.structured_output` | Asks the model for structured output. |
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
to fit: `✓` pass, `!` warning, `×` failure. The detail pane shows the
selected check with its state word, the result, fix guidance when available,
`checked HH:MM` and the related path when one applies, and the buttons
`[f] Fix: …` (for a warning or failure that has a fix), `[t] Test: …` (when
the area has a test), `[l] Open log`, and `[c] Copy report`.

The first row of the tab shows `N pass · N warn · N fail`, the time of the last
run, and `[r] Run again`. The Settings navigation badge shows `N W` for warnings or `N F` for
failures, and the tab label shows `●N` when the last run has warnings or
failures. New optional checks appear as warnings and do not change the
existing `stenographer doctor` exit status. The refine service check asks the
configured Ollama host for its model list only while refine is on; it sends
no transcript text.

| Key | Action |
| --- | --- |
| `up` / `down` | Select a check. |
| `r` | Run the checks again. |
| `f` | Fix: open the related Settings tab and row, or the Quick setup or Models dialog. |
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
