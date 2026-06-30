<!--
SPDX-License-Identifier: GPL-3.0-or-later
-->

# 10 — Packaging

## Dependencies

- **Reads:** `00-overview.md` (component list, module paths).
- **Blocks:** every component doc (they cite Python deps declared here)
  and `08-process-model.md` (the systemd unit is shipped from this
  doc).

## Goal

Define the `pyproject.toml`, the Python and system dependencies, the
shipped asset layout, the model cache location, and the install story.
A coding agent implementing any component can pull this doc to know
exactly which imports are available and which `PATH` binaries to shell
out to.

## pyproject.toml skeleton

```toml
[project]
name = "stenographer"
version = "0.1.0"
description = "Local, offline, Wayland push-to-talk / toggle dictation."
readme = "README.md"
license = { text = "GPL-3.0-or-later" }
requires-python = ">=3.14"
license-files = ["LICENSE"]
authors = [{ name = "stenographer contributors" }]

dependencies = [
    "sounddevice>=0.4.7",
    "numpy>=2.0",
    "faster-whisper>=1.0.0",
    "python-evdev>=1.4",
    # tomllib is in the stdlib on 3.11+; this project pins 3.14.
]

[project.optional-dependencies]
dev = [
    "ruff>=0.5",
    "pytest>=8",
    "pytest-asyncio>=0.23",
]

[project.scripts]
stenographer = "stenographer.cli:main"

[project.urls]
Homepage = "https://example.invalid/stenographer"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/stenographer"]
include = [
    "src/stenographer/assets/sounds/*.wav",
    "src/stenographer/assets/sounds/*.ogg",
]

[tool.ruff]
line-length = 100
target-version = "py314"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "N", "SIM", "RUF"]

[tool.pytest.ini_options]
addopts = "-ra"
testpaths = ["tests"]
```

## Source layout

```
src/stenographer/
├── __init__.py
├── cli.py
├── config.py
├── errors.py
├── hotkey/
│   ├── __init__.py
│   ├── binding.py        # parse / validate hotkey.binding strings
│   ├── listener.py       # python-evdev loop
│   └── state_machine.py  # hybrid PTT / toggle FSM
├── audio/
│   ├── __init__.py
│   ├── capture.py
│   └── feedback.py
├── asr/
│   ├── __init__.py
│   ├── model.py          # WhisperModel lifecycle
│   └── worker.py         # background thread that runs transcribe()
├── output/
│   ├── __init__.py
│   ├── inject.py         # wtype wrapper
│   └── clipboard.py      # wl-copy / wl-paste wrapper
├── session.py            # per-utterance orchestrator
├── capabilities.py       # startup probe (wtype, wl-copy, pw-play, ...)
└── assets/
    └── sounds/
        ├── ptt_on.wav
        ├── ptt_off.wav
        ├── toggle_on.wav
        ├── toggle_off.wav
        ├── error.wav
        └── transcribe_done.wav

tests/
├── conftest.py
├── test_config.py
├── test_hotkey_state_machine.py
├── test_audio_capture.py
├── test_asr.py
├── test_audio_feedback.py
├── test_clipboard.py
├── test_text_output.py
└── fixtures/
    └── (small wavs)

packaging/
├── stenographer.service.in   # systemd user unit template
└── model-download.sh         # invoked by `stenographer model download`
```

## Python dependencies (pinned to a known-working floor)

| Package         | Version  | Used by                                |
|-----------------|----------|----------------------------------------|
| `sounddevice`   | `>=0.4.7`| `audio/capture.py`                     |
| `numpy`         | `>=2.0`  | `audio/capture.py`, `asr/worker.py`    |
| `faster-whisper`| `>=1.0.0`| `asr/model.py`, `asr/worker.py`        |
| `python-evdev`  | `>=1.4`  | `hotkey/listener.py`                   |
| `tomllib`       | stdlib   | `config.py`                            |
| `argparse`      | stdlib   | `cli.py`                               |
| `logging`       | stdlib   | everywhere                             |
| `pathlib`       | stdlib   | everywhere                             |
| `subprocess`    | stdlib   | `audio/feedback.py`, `output/*`        |
| `dataclasses`   | stdlib   | `config.py`                            |
| `threading`     | stdlib   | `asr/worker.py`, `audio/capture.py`    |
| `enum`          | stdlib   | `hotkey/state_machine.py`              |

## System dependencies (NOT pip-installed; resolved at runtime)

| Binary           | Package on Debian/Ubuntu      | Package on Fedora     | Used by                            |
|------------------|-------------------------------|-----------------------|------------------------------------|
| `wtype`          | `wtype`                       | `wtype`               | `output/inject.py`                 |
| `wl-copy`        | `wl-clipboard`                | `wl-clipboard`        | `output/clipboard.py`              |
| `wl-paste`       | `wl-clipboard`                | `wl-clipboard`        | `output/clipboard.py`              |
| `pw-play`        | `pipewire-utils`             | `pipewire-utils`     | `audio/feedback.py` (preferred)    |
| `paplay`         | `pulseaudio-utils`            | `pulseaudio-utils`    | `audio/feedback.py` (fallback)     |
| `python3-evdev`  | `python3-evdev`               | `python3-evdev`       | transitive, required by python-evdev |

Additionally, the **user** must:
- Be a member of the `input` group (or have a uaccess rule for the
  keyboard device), or `hotkey/listener.py` cannot grab it.
- Have a working PipeWire **or** PulseAudio session.
- Have a working Wayland session with a compositor that accepts the
  `zwp-input-method-protocol-unstable-v1` protocol (wlroots, Hyprland,
  Sway, KWin, Mutter all qualify).
- Be the active user when running the daemon (sounddevice opens the
  default mic, which the user's PipeWire / PulseAudio session owns).

## Capability probe (`capabilities.py`)

```python
@dataclass(frozen=True)
class Capabilities:
    has_wtype: bool
    has_wl_copy: bool
    has_pw_play: bool
    has_paplay: bool
    has_input_group: bool
    has_mic: bool
    has_asr_model: bool

    @classmethod
    def probe(cls, cfg: Config) -> "Capabilities": ...
```

The probe is run **once**, at startup, from `cli.py:main` before any
listener is registered. The result is passed by reference to every
component; components that depend on a missing capability MUST degrade
per `09-error-handling.md` rather than raise.

## Asset packaging (sound cues)

Cue files live in `src/stenographer/assets/sounds/` and are shipped in
the wheel via Hatch's `include` glob above. The `04-audio-feedback.md`
spec defines the exact audio content (frequencies, durations, sample
rate) that the implementation must produce if it generates them
programmatically, **or** the asset files if it ships pre-rendered WAVs.
v1 ships pre-rendered WAVs; the spec allows either.

The on-disk layout of installed cues (after `pip install`) is:

```
<site-packages>/stenographer/assets/sounds/{ptt_on,ptt_off,toggle_on,
    toggle_off,error,transcribe_done}.wav
```

The `04-audio-feedback.md` spec also defines the resolution order for
cue paths: explicit `feedback.cues.<name>` from config > bundled asset.

## Model cache

faster-whisper downloads to the HuggingFace Hub cache by default
(`$XDG_CACHE_HOME/huggingface/hub/`, default
`~/.cache/huggingface/hub/`). v1 does **not** relocate the cache.

If the model is missing, the probe marks `has_asr_model = false`. The
daemon then prints:

```
stenographer: ASR model not found at <path>.
  Run `stenographer model download` to fetch it, or set
  stenographer.asr.model in your config to a local path.
```

and exits 78.

`stenographer model download` resolves the configured
`asr.model` identifier and runs `huggingface-cli download <id>` (which
ships with `huggingface-hub`, a faster-whisper transitive dep).

## systemd user unit

File: `packaging/stenographer.service.in`. Rendered to
`~/.config/systemd/user/stenographer.service` by `make install` (or by
hand). The unit uses the `%h` specifier for the user's home and binds
to the graphical session target.

```ini
[Unit]
Description=stenographer dictation daemon
After=graphical-session.target pipewire.service pulseaudio.service
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=%h/.local/bin/stenographer run
Restart=on-failure
RestartSec=2

[Install]
WantedBy=graphical-session.target
```

The daemon is **not** a D-Bus service in v1; there is no socket
activation, and the one-shot CLI does not communicate with the daemon.

## Install story (documented in README, not implemented here)

- `pipx install stenographer` for single-user install.
- `pip install --user stenographer` as the alternative.
- A future distro package (`stenographer` on Debian / Fedora) is out of
  scope for this doc.

## Out of scope (v1)

- AUR / Homebrew / Nix package.
- Distro packages.
- D-Bus activation.
- Logging to syslog (v1 logs to stderr + `$XDG_STATE_HOME/stenographer/stenographer.log`).

## Open questions

- **Compute type default.** `int8_float16` requires a recent CPU. Should
  the default be `"int8"` (CPU-only) and let users opt into
  `int8_float16`? v1 ships `"int8_float16"`; revisit after first user
  reports.
- **Test sound assets.** Should the wheel include separate, shorter
  cue files for the test suite, or should tests mock `pw-play`? v1
  spec defers this to `04-audio-feedback.md`.
