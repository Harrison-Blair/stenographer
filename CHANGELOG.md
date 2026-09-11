<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Changelog

These notes cover every published stable release. They describe observable
behavior and release packaging, with internal planning and generated commit
lists left out.

## [v0.13.0] - 2026-09-11

This release adds an optional local cleanup stage that turns dictated speech
into written text without leaving your machine.

- Adds refine: an off-by-default stage that sends each dictation of ten or
  more words to a local Ollama model, collapses self-corrections, removes
  hesitation fillers, and renders spoken lists as lines. Meaning is preserved;
  nothing is summarized, answered, or added. On any error or timeout the
  original transcript is delivered unchanged.
- Defaults to `gemma4:e2b` over loopback, chosen by the new
  `scripts/refine_bench.py` benchmark. Any installed Ollama model can be
  configured; a non-loopback host is reported in the daemon banner.
- `stenographer model download` now offers to fetch both the ASR and refine
  models; `--asr` and `--refine` select one. `stenographer transcribe` gains an
  explicit `--refine` flag.
- The overlay shows a Refining state, and local analytics record refine
  timing and outcomes as numbers only.

## [v0.12.3] - 2026-09-11

This maintenance release strengthens reliability and test coverage.

- Adds broad unit coverage using real substitutes and isolates tests from user
  directories.
- Fixes Windows portability checks and removes timing-sensitive test
  assumptions.
- No intentional user-facing behavior changes were introduced.

## [v0.12.2] - 2026-09-11

This release makes cancellation easier to reach and improves the project’s
documentation and distribution structure.

- Press `Escape` to cancel an active recording or delivery. The audio and
  transcript are discarded, and nothing is pasted.
- Adds the GitHub Pages site and a new user guide.
- Reorganizes the library, CLI, and overlay code and simplifies the packaged
  distribution.
- Removes the separate desktop settings application while preserving local
  configuration, models, analytics, and logs.

## [v0.12.1] - 2026-09-11

This release adds private numeric usage statistics and makes the default
hotkey workflow more flexible.

- Adds durable local analytics and the `stenographer stats` command for
  viewing, exporting, and deleting numeric dictation statistics.
- Adds an independent desktop settings and analytics application.
- Makes hybrid hotkey mode the default: hold to speak, or tap to latch a
  recording.
- Adds `setup --default` for writing an annotated default configuration.
- Improves structured logging, per-utterance diagnostics, doctor reports,
  native packaging, and overlay lifecycle feedback.

## [v0.11.6] - 2026-08-24

Installing and keeping a Linux installation current is now simpler.

- Adds a curl-piped quick installer for verified Linux x86_64 and AArch64
  release bundles.
- The installer verifies SHA-256 checksums and supports leaving the service
  stopped for later configuration.
- Adds opt-out update notices based on a metadata-only GitHub release check,
  at most once per day. Dictation data is never sent.

## [v0.11.5] - 2026-08-24

This maintenance release consolidates host-specific behavior behind the
platform contract and prepares the project for broader portability.

- Reorganizes Linux overlay backends, capability handling, and CLI support
  around shared platform boundaries.
- Extracts more pure decision logic and shared console behavior for consistent
  operation across supported environments.
- Fixes an import regression and makes path-rendering tests independent of the
  host operating system.

## [v0.11.0] - 2026-08-22

This release improves feedback customization and isolates operating-system
integration from the dictation core.

- Adds selectable sound packs, including `legacy`, `warm-desk`,
  `soft-electronic`, and `minimal-ui`, with preview and custom-pack support.
- Moves Linux integrations behind a platform boundary so the core remains
  portable.
- Improves X11 fallback when a Wayland probe does not succeed.
- Standardizes key-binding names across input providers and adds validation for
  the new sound assets.

## [v0.10.0] - 2026-08-22

This major release reauthors the dictation stack around a smaller, more
portable set of components.

- Adds the reworked audio capture, transcription worker, paste delivery,
  lifecycle overlay, daemon, `doctor`, and `devices` flows.
- Adds interactive setup with microphone spectrum-floor calibration.
- Adds hotkey hotplug recovery, safer modifier handling, and stronger runtime
  recovery boundaries.
- Ships a standalone per-user Linux bundle and installer, including native
  shell completions.

## [v0.9.5] - 2026-08-02

Incremental dictation is more responsive during pauses and more tolerant of
slow or failed decoding.

- Skips redundant re-decodes during pauses, trims sustained silent tails, and
  reuses valid interim results when recording ends.
- Improves recovery from slow or failed incremental decoding and filters weak
  or hallucinated flushed tails.
- Adds `asr.cpu_threads` and timeout controls for incremental work.
- Adds `stenographer bench --incremental` for replaying and measuring
  incremental transcription.
- Restructures ASR, configuration, overlay, systemd, and transcript delivery
  internals while preserving the intended behavior.

## [v0.9.4] - 2026-07-24

This release makes silence handling and release installation safer.

- Adds an audio-energy gate, Silero VAD, hallucination protection, and bounded
  generation for speech surrounded by silence.
- Improves checksum and download reporting in the update and install flows.
- Adds opt-in startup update notices in the HUD, with desktop notification
  fallback.
- Adds `scripts/reinstall.sh` for rebuilding and reinstalling development
  bundles.

## [v0.9.3] - 2026-07-20

This maintenance release protects active dictation through shutdown and keeps
the HUD stable.

- Drains active work during bounded shutdown so a final utterance is not lost.
- Clipboard-paste mode preserves the complete transcript beyond the configured
  output character cap.
- Keeps the HUD at one size and shows the running version without preview
  resizing or repositioning it.

## [v0.9.2] - 2026-07-19

This release adds live feedback while recording and more control over
transcription vocabulary.

- Adds incremental transcript previews and a GTK layer-shell HUD with a live
  microphone spectrum.
- Adds `stenographer status` for checking daemon state.
- Adds `asr.hotwords` and `asr.initial_prompt` for vocabulary biasing.
- Changes the default model to `faster-whisper-medium.en`; the default model
  download is about 1.5 GB.

## [v0.8.3] - 2026-07-17

Live streaming dictation is now available, with delivery and hotkey controls
built around it.

- Pastes confirmed words at the cursor while recording continues, with
  append-only spacing and capitalization formatting.
- Trims tail silence using the recording’s noise floor and bounds streaming
  decode windows.
- Adds configurable push-to-talk, toggle, and hybrid trigger modes, with
  push-to-talk as the default for this release.
- Adds `transcribe --raw` and a full-transcript clipboard fallback when live
  delta delivery fails.
- Fixes streaming liveness, clipboard, shutdown, and frozen-binary packaging
  edge cases.

## [v0.7.7] - 2026-07-09

The default installation now uses a smaller speech model.

- Changes the default model to `faster-distil-whisper-medium.en`, reducing the
  default download from roughly 3 GB to roughly 800 MB.
- Keeps interactive choices for smaller or more accurate models.
- Adds desktop notification dependencies to the documented and automated
  installation setup.

## [v0.7.5] - 2026-07-09

Installing and managing the user service now happens from the release bundle.

- Adds a self-bootstrapping installer that downloads and verifies the
  standalone binary, configures the installation, offers dependency setup,
  downloads the model, and prepares systemd.
- Adds dedicated `enable`, `start`, `stop`, and `disable` commands.
- Adds `enable --no-start` for configuring an installation before starting the
  service.

## [v0.7.3] - 2026-07-08

This maintenance release fixes release-status reporting.

- The release badge now updates after a successful release workflow completes,
  avoiding stale status caused by workflow timing.
- No application behavior changed.

## [v0.7.2] - 2026-07-08

This release adds tools for measuring transcription and begins the live
streaming work.

- Adds the `stenographer bench` command for comparing models, beam sizes,
  compute types, word error rate, and streaming behavior.
- Adds an experimental LocalAgreement streaming transcription API.
- Adds a combined `build-and-install.sh` helper and automatic release-build
  reporting.

## [v0.6.10] - 2026-07-06

Hotkey control and cancellation are more reliable for everyday dictation.

- Adds double-tap toggle activation, configurable cancellation, and recovery
  from missed key releases.
- Cancellation stops active capture and pending transcription work before
  delivery.
- Adds shell completion support and cancel/discard audio cues.
- Filters probable silence from streaming and clipboard output.

## [v0.6.9] - 2026-07-03

Long recordings and quiet input are handled more safely.

- Adds silence-aware segment flushing and recording-length limits.
- Filters likely hallucinations produced over silence before injection or
  clipboard delivery.
- Adds the `devices` command, more resilient notifications, rotating logs, and
  safer partial injection behavior.

## [v0.6.8] - 2026-07-01

Idle model memory use is lower and model lifecycle state is easier to follow.

- Loads the speech model on first daemon use and unloads it after a configurable
  idle period.
- Reports model loading, readiness, and idle unloading through notifications
  and audio cues.

## [v0.6.7] - 2026-07-01

Audio setup now works across a wider range of devices.

- Adds sample-rate and channel-count fallback, with resampling to the configured
  rate when needed.
- Improves startup notifications and microphone device reporting.
- Updates standalone packaging so system PortAudio libraries remain external
  and are found correctly at runtime.

## [v0.6.6] - 2026-07-01

Standalone HTTPS operations now use a bundled certificate authority bundle.

- Adds Certifi for more reliable TLS verification during update checks and
  downloads.
- Includes Certifi in frozen standalone builds.

## [v0.6.5] - 2026-07-01

Standalone builds and update validation are more tolerant of packaging
details.

- Refreshes the editable build environment before packaging.
- Accepts valid frozen bundles whose internal PyInstaller layout differs from
  the previous assumed layout.

## [v0.6.4] - 2026-07-01

Release update verification now handles archived assets correctly.

- Fixes checksum-file discovery when a release asset includes an archive suffix
  such as `.tar.gz`.

## [v0.6.3] - 2026-07-01

Upgrades and installation guidance are clearer.

- `stenographer update` now displays the available release notes.
- Documents the bundled build-and-install path and systemd user-service setup.
- Cleans up the release-build workflow and its status reporting.

## [v0.6.1] - 2026-07-01

Initial packaged release of local, offline Wayland dictation.

- Adds configurable hotkeys, Whisper transcription, clipboard and paste
  delivery, audio cues, notifications, and systemd user-service integration.
- Adds standalone binary packaging and installation support.
- Keeps dictation local while making model downloads explicit.
