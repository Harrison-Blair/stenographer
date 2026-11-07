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
| `q` / `ctrl+c` | Quit. The hub asks first while a recording, a relabel pass, or a file job runs, and while Settings has unsaved changes. |

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
that lists each action: stop and save the recording, skip the running relabel,
and cancel the running file job. Press `y`, `q`, or `ctrl+c` (or click the
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
stays open. The save and the speaker relabel pass run in the background: the
transcript title shows `relabeling…` and the top line shows
`relabeling N of M` until the pass ends. While it runs, the saved session is
busy: `rename busy` shows in the speaker bar, `[r] Rename…` is disabled, and `r` shows the notice
`session busy`. You can press `space` to record again while the pass runs, and
several stopped sessions can relabel at the same time. When the pass ends, the
transcript ends with a marker line such as
`── saved · 31 phrases · mic.flac 88 MB · system.flac 0.2 MB ──` (only the
audio files that exist). Press `o` to show the session in Library. If the save
fails, also for an older session that was still saving, a notice shows the error
and the REC panel shows `! SAVE FAILED` with that session until the next recording
starts; `o` still shows what the session folder holds. If several saves fail, the
panel lists each error and session, and each press of `o` shows the next session.

If you quit while a relabel pass runs, the quit question lists it. Press `y` to
skip each pass; the hub waits until each session has saved its files, then
quits. The saved session keeps the labels that it had during the recording.
Press `n` to keep the hub open.

Each meter shows 18 frequency bands in 8 rows, the band labels
`100 200 400 800 1k6 3k2 6k4`, the level and the 3-second peak in dBFS, and a
speech light (`● speech` or `○ quiet`) from the voice detector of the source.
While no recording runs, a meter shows a dotted grid and `not recording`.
Press `m` or `s` to turn a source on or off. During a recording, the key
changes the running session. Before a recording, the key chooses the sources
of the next recording; a source that is off shows `off · press m to enable` (or
`s`). System audio captures the current output mix, not separate applications.

Press `d` (or click `[d] change device…`) while no recording runs to choose the
input device. The dialog lists each input device and `Settings default`. A
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
phrases when there are any, and `! mic audio not saved` when a source's audio
cannot be written. `[r] Rename…` sits in the transcript title row. After such a failure the source keeps
transcribing, its audio file ends at the failure, and the recording still saves
its transcript. Press `r` (or click `[r] Rename…`) to open the Rename speaker dialog:
choose the speaker, type the new name, and press `enter` (or click `[enter] Rename`); `escape` cancels. During a recording, the
rename changes the live labels. On a saved session, the rename writes a new
transcript revision of that session.

### Prepare the models

Record uses the same speech model as dictation and file jobs: Underdog Bark 3.0
Pro, int8 ONNX on the CPU. It also uses separate voice-activity and speaker
models. Download each model only when you choose to:

```sh
stenographer model download --asr
stenographer model download --live
```

`--asr` builds the speech model on your machine and downloads the Silero
voice-activity model. It needs `python3-venv`, 10 GiB of free disk, and about
10.2 GiB of RAM; see [build the speech model](usage.md#build-the-speech-model).
`--live` downloads the Silero voice-activity model and the English speaker
model. Record does not download models for you.

### Separate the speakers in a room

When several people share one microphone, turn on microphone diarization:
set `live.diarize_mic` (default `false`) on the Live tab of Settings. A new
recording then labels microphone speakers `Room 1`, `Room 2`, and so on
(speaker IDs `room-1`, `room-2`), apart from the system speakers (`Speaker 1`,
...). Microphone and system voices are never clustered together, so a room
voice and a system voice never share a label. `r` lists room speakers with the
system speakers. The setting applies when a recording starts; Record has no
toggle for it. With the setting off, microphone lines are `You`.

Limits:

- During a recording, labels are per phrase. Voice-activity detection splits
  phrases at pauses, so a speaker change without a pause stays in one phrase under
  one label until the recording is saved.
- Room labels are similarity estimates, like system labels. They can split one
  person or merge several people.
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

### Relabel rules

During a recording, stenographer regroups speakers every 30 seconds of recording. It runs the batch speaker-label pass over the phrases so far, separately for system phrases and, when microphone diarization is on, microphone phrases. Between passes, each new phrase joins the nearest known speaker, so a new voice can show under another speaker's label until the next pass. Only the first phrase of a source creates a speaker without a pass. A pass can move earlier lines to a different speaker. Known speakers keep their numbers and given names from pass to pass during the recording. The speaker list shows only speakers that have lines.

When you stop and save a session, stenographer runs a batch speaker-label pass
on the saved system phrases, and separately on the microphone phrases when
microphone diarization is on, and stores the revised labels in a new transcript
revision. This pass also runs when you confirm quit during a recording. Speaker
labels are similarity estimates, not reliable identity checks. A minor voice gets its own label only if it has at
least 15 seconds of phrases that are each at least 2 seconds long within a
30-second window and at least two-thirds of its speech in those sustained
phrases, or if it has at least 20% of the top speaker's speech time.
Otherwise, stenographer merges that voice into the most similar voice. Short or
sparse phrases can therefore remain under another speaker's label.

The saved speakers come from the saved audio. For each source with lines,
stenographer runs the bundled pyannote segmentation model on the whole source,
keeps the pieces of speech of 0.5 seconds or more, and groups the pieces with the
rules above. A line gets the speaker with the most overlap in seconds. A line where
another voice holds a run of at least 1 second is cut, each part is decoded again,
and each part gets the speaker of its run. If a part has no text, the line stays
whole. Where two voices overlap, the voice that started last holds the time. A line
with no piece stays and gets the closest voice. A source with no saved audio, or one
where the model finds no speech, groups whole lines. File jobs, Re-diarize, and
Re-transcribe use the same method; an older recording changes only when you press
`d` or `t`. This pass holds the whole source in memory and can use up to about 2 GB
per hour of audio.

When a pass merges speakers, the merged speaker keeps the number of the speaker with the most speech that an earlier pass grouped, and a renamed speaker chooses before an unnamed one. If two renamed speakers merge, only one name can stay on the merged speaker. When the session saves, speakers are numbered from 1 in order of first appearance, with no gaps, so a number can change once at save, for example `Room 3` becomes `Room 2`. Given names stay. If you skip the end pass, or it fails, stenographer saves the speakers and names shown on screen, numbered the same way, and a failure shows the reason on the saved Record screen. If that save fails, the stop shows as a failed save. File jobs and re-diarize number clusters by first appearance and keep each renamed label on one cluster, the one with the most shared speech time. Rename several speakers to the same name
to merge their displayed labels; this does not change their speaker IDs. The
clustering threshold is 0.50; it was tested on only three clips, so labels are
not reliable identification.

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

- **Recording:** `labels` is `live` for live speaker labels, also after a
  skipped or failed end pass, `relabeled` when the relabel pass or a re-diarize
  ran, a revision method such as `rename` or
  `re-transcribe`, or `! interrupted` when the recording stopped without a
  clean save.
- **File session:** `labels` is the name of the source file.
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
| `d` | Re-diarize the session. This also needs the speech model. A file session cannot: use Re-transcribe. |
| `t` | Re-transcribe the session and group its speakers again, so labels can change. This also needs the speaker model when a source has speaker separation. |
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
can still be revised. Re-labeling uses the same speaker similarity limits as the
Record screen. Re-diarization relabels microphone lines as `Room N` speakers only
for a session recorded with microphone diarization (`"diarize_mic": true` in its
`session.json`). For other sessions, including older ones, it relabels system
lines only and microphone lines stay `You`. `r` can rename room speakers.

A long phrase can hold more than one speaker. For phrases of 6 s or more on a source with speaker separation, Stenographer compares overlapping 3 s slices, one every 0.75 s, with the voices of the grouped speakers. When another speaker clearly leads for two slices in a row, it cuts the phrase at the quietest point near the change, decodes each part again, and groups the speakers again, so one line becomes several, each under its own speaker. If any part decodes to no text, the phrase stays whole, so no words are lost. Overlapping speech stays on one line. A microphone without diarization stays `You`.

This runs at four points: during the relabel pass when a recording stops (`q` skips it with that pass); on Re-diarize, which therefore also needs the speech model; on Re-transcribe, which also needs the speaker model when a source has speaker separation; and at the end of a file job, which keeps a speaker count you set. Re-transcribe now groups speakers again, so speaker labels can change; given names carry over. On an imported file it groups automatically and ignores a count set at import, so it can change the speaker count. A file session with one speaker keeps its labels and is not split. If all phrases of a file session are shorter than 1.2 s, Re-transcribe gives it one speaker. Stopping a long recording takes a little longer: about 1% of its length on the sessions measured.

### Transcribe a file

Press `n` or click `[n] + Transcribe a file…` to open the Transcribe a file
dialog. It has a file browser and the job options:

- The browser starts in your home folder. It lists `..`, the folders, and the
  supported audio files of the current folder, with durations when soundfile can determine them. Hidden folders are listed; search with a leading dot to show hidden audio files. If a folder cannot be read, the browser shows the reason and retains `..` for navigation. Press `up` and `down` (or click a row) to select
  an entry. Press `enter` on a folder to open it. Press `/` to search names in
  the current folder; `escape` clears the search.
- **Separate speakers** (`s`): identify and label speakers. On by default.
- **Speaker count** (`c`): `auto` (the default) or a whole number above 0. Any
  other value shows `× Speaker count must be auto or a whole number above 0`
  and the dialog stays open.
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
  (mic) or `Speaker 1` (system); without Separate speakers, mic lines are
  `You`. Earlier renames of the replaced source do not carry over.
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
| General | hotkey, sound and overlay feedback, update check, log level, delivery, and analytics |
| Audio | input device, minimum speech level, maximum recording length, and spectrum floor |
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
| Update check | `feedback.update_check` | When the dictation daemon starts, checks release metadata and shows an update notice. |
| Log level | `feedback.log_level` | The minimum level of console log messages. |
| Copy original | `delivery.copy_original` | For the Agent key, and only when cleanup changed the text, copies the original transcript too. |
| Restore clipboard | `delivery.restore_clipboard` | Restores the previous clipboard item after dictation delivers its text. |
| Restore delay | `delivery.restore_delay_ms` | The wait, in milliseconds, before the clipboard is restored. |
| Usage history | `analytics.enabled` | Stores local numeric usage history of dictation and `stenographer transcribe`. No audio or transcript text is stored. |
| Resource profiling | `analytics.resource_profiling` | With Usage history on, measures local resource use during utterances. |
| Microphone | `audio.input_device` | The audio input device name or index for dictation and Record. Blank uses the default. Record's `d` key can choose another device for its next recording. |
| Minimum speech level | `audio.min_speech_rms` | Hotkey dictation ignores audio below this speech energy level. Zero disables the gate. `stenographer transcribe` only reports the result. Record and file jobs do not use it. |
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
| input | input access, microphone, hotkey, sounds |
| engine | speech model, voice models, refine service, system audio, system service |
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

The microphone test lists the input devices and does not capture audio. The
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
- **Models** shows the speech model and the two voice models with their size,
  as present or missing or corrupt. Press `enter` on a missing or corrupt model
  to download it; a corrupt file is replaced only after the download is
  verified. One download runs at a time; a notice shows when another one is
  running.
- **Defaults** writes the default configuration after a confirmation and
  keeps the current file as a timestamped backup.

The `stenographer setup` and `stenographer doctor` commands do not change.

The Record meters use the saved spectrum floor for each new recording. Returning
to a saved recording refreshes its transcript; deleting that session clears Record.
Library shows search progress and read errors, including alongside file jobs.
Speaker rename waits for the session details to load. File transcription requires
a valid configuration before the dialog opens; when speaker separation is off,
the speaker count is disabled and ignored. Switching Settings tabs keeps a valid
inline edit and stays on the current tab if the value is invalid. Model status
refreshes when the dialog opens and before or after a download.
