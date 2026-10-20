<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Terminal hub

Run `stenographer` from a terminal to open the hub. It opens on Live and does
not start recording until you press `space`. If stdin or stdout is not a
terminal, the command prints help instead. The hub is a local, keyboard-driven
interface with six sections. The daemon and existing commands keep their
current behavior. In particular, `stenographer live` still opens its
standalone live app with its existing flags. See the [live guide](live.md).

## Sections and keys

Press `1` to `6` to select a section:

| Key | Section | Purpose |
| --- | --- | --- |
| `1` | Live | Record microphone and system audio, and view the transcript. |
| `2` | Files | Queue audio files for transcription and export. |
| `3` | Sessions | Review and manage saved live sessions. |
| `4` | Config | Edit and save settings. |
| `5` | Setup | Check six setup areas and edit related settings. |
| `6` | Doctor | Review system checks, warnings, and suggested fixes. |

The key hints at the bottom of the hub change with the selected section.
Arrow keys move between items in Files, Sessions, and Config. Keys that have
a meaning in more than one section perform the action for the selected section.
Scrollbars stay visible. Their thin accent-colour thumbs are the only exception
to the no-background rule; tracks and corners stay transparent.

## Hub lifecycle

Live is idle when the hub opens. Press `space` to start recording; while a
session is active, `space` pauses or resumes it. Recording continues when you
change sections. The hub runs recording start, stop, and save work in the
background so the interface can remain responsive.

Press `q` or `ctrl+c` to quit. When a recording is active, the hub asks for
confirmation before it stops and saves the session. Press `y`, `q`, or
`ctrl+c` to confirm; press `n` or `escape` to cancel. When a Files job is
running, the hub asks before it cancels the job and quits. A cancelled Files
job does not leave a partial output file. If a start, stop, or save operation
is still in progress, wait for its status to finish before you send another
quit key.

If you have unsaved Config changes, the hub asks whether to save, discard, or
stay in the current section before it navigates away or quits. A successful
save keeps a timestamped `config.toml.bak-<time>` backup and preserves
comments and settings that the editor does not know about.

## Live

The Live section has a REC panel with elapsed time and MIC and SYSTEM panels
with the device, waveform meter, and dBFS level. A sidebar card shows the model,
compute type, queue, failed count, and CPU use. The transcript opens in mixed
view, with one time-ordered stream and speaker labels. Press `v` to switch to
split view, where microphone and system lines appear in separate, captioned
columns in time order. Press `v` again to return to mixed view. The key hints
show the section keys `1` to `6`. Press `m` to toggle microphone input, `s` to
toggle system audio, and `r` to rename a system speaker. System audio captures
the current output mix, not separate applications.

When you stop and save a session, stenographer runs a batch speaker-label pass
on the saved system phrases and stores the revised labels in a new transcript
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

## Files

Files has a browser, transcription options, a job queue, and a result preview.
The browser lists WAV, FLAC, OGG, MP3, Opus, AAC, M4A, MP4, MKV, WebM, and WMA
files. Files that `soundfile` can read use that library. M4A and AAC files use
the system `ffmpeg` executable; other files that `soundfile` cannot read also
use `ffmpeg`. Stenographer does not bundle FFmpeg. Install it with your system
package manager. Doctor reports when `ffmpeg` is missing, and a file job that
needs it cannot start without it.

Select one or more files in the browser and press `enter` to queue them. Jobs
run one at a time in the background. The queue shows each job's state, stage,
progress, and estimated time remaining. Select a job to see its transcript
preview. Press `x` while the queue has focus to cancel the selected job; press
`e` to open the folder for a saved result.

The options are:

- **Diarize:** identify and label speakers. This is on by default.
- **Speaker count:** choose `auto` or a positive number. `auto` is the default.
  A number requests a fixed speaker count for that Files job.
- **Refine:** apply the configured text-refinement service. This is off by
  default for Files jobs.
- **Output format:** choose Markdown (`md`), JSON Lines (`jsonl`), SubRip
  subtitles (`srt`), or plain text (`txt`). Markdown is the default.
- **Output folder:** choose where to save the result. The default is
  `$XDG_DATA_HOME/stenographer/files/`, or
  `~/.local/share/stenographer/files/` when `XDG_DATA_HOME` is unset.

Press `tab` to move focus between the browser, queue, and options. In the
browser, press `/` to search, `space` to select a file, and `enter` to open a
folder or queue the selected files. In Options, press `o` to open or close the
panel; use the arrow keys to choose a setting and `enter` or `space` to edit
it. The output format cycles through its four choices. Speaker count accepts
`auto` or a positive integer.

## Sessions

Sessions shows storage count and audio size in the sidebar card. Its saved
session list and selected-session detail use separate bordered panels. The list
shows each session's duration and speaker count. Select a session with the up
and down arrows. The detail view shows each speaker's talk time, microphone
and system activity, whether labels were revised, and the transcript. The
active recording does not appear in this list until it has been saved.

| Key | Action |
| --- | --- |
| `p` | Play or stop session audio with `pw-play`. |
| `d` | Re-diarize the saved session. |
| `t` | Re-transcribe the saved session. |
| `r` | Rename a speaker in the selected session. |
| `x` | Export the transcript as `md`, `jsonl`, `srt`, or `txt`. |
| `delete` | Delete the selected session after confirmation. |

Re-diarization and re-transcription write new transcript revisions and keep
previous revisions. Re-labeling uses the same speaker similarity limits as the
Live section.

## Config

Config edits `config.toml` by group: hotkey, audio, ASR, live, refine,
feedback, analytics, and delivery. It shows one shared set of ASR settings for
dictation, Live, and Files. The default model is
`deepdml/faster-whisper-large-v3-turbo-ct2`; other defaults include `int8`
compute, beam size `1`, and VAD filtering. Model downloads are explicit. Run
`stenographer model download --asr` to download the configured model. An
existing configuration with an explicit `stenographer.asr.model` keeps that
value when the default changes.

| Key | Action |
| --- | --- |
| `left` / `right` | Select a settings group. |
| `up` / `down` | Select a setting. |
| `enter` | Edit the selected setting. |
| `u` | Undo the last edit. |
| `shift+d` | Reset the selected setting to its default. |
| `/` | Search setting names. |
| `ctrl+s` | Save changes and keep a timestamped backup. |

Settings apply to new sessions and jobs. Work that is already running keeps
its current settings.

## Setup and Doctor

Setup has six steps: input access, microphone, hotkey, models, sounds, and
system service. Tests check the selected item. The microphone test lists
available devices and does not capture audio. The sound test plays a preview.
Model downloads require a separate confirmation. Setup does not start or
restart the system service.

| Key | Action |
| --- | --- |
| `enter` | Complete or advance the current step. |
| `b` | Go back one step. |
| `s` | Skip the current step. |
| `t` | Test the current step. |
| `e` | Edit the setting for the current step. |
| `m` | Start a model download after confirmation. |
| `shift+q` | Use quick setup for steps 1 to 3. |
| `shift+d` | Write the default configuration. |

Doctor groups capability checks and shows details and fixes for selected
checks. New optional checks appear as warnings and do not change the existing
`stenographer doctor` exit status. Press `r` to run the checks again, `enter`
to show details, `f` to open the related Setup step, `l` to open the log, or
`c` to copy the report. Recent warnings are shown without transcript text.
