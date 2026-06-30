<!--
SPDX-License-Identifier: GPL-3.0-or-later
-->

# 09 — Error handling

## Dependencies

- **Reads:** `00-overview.md` (components, capability probe).
- **Reads:** `10-packaging.md` (system deps, capability list).
- **Blocks:** every component doc. They MUST honour this policy.

## Goal

Define a single, consistent policy for how every component reacts to
failures — both recoverable and fatal. Components MUST NOT invent their
own error behaviour; they MUST consult this doc and use the
`stenographer.errors` module's helpers.

## Two-tier policy

1. **Capability miss at startup** -> degrade (skip that feature,
   continue) or exit 78 (`EX_CONFIG`).
2. **Runtime failure** -> log + fire the `error` cue (if audio feedback
   is available) + (optionally) skip the affected step + continue.

The exact split is decided per capability below.

## Capability matrix (startup)

| Missing capability | Effect                                                                  |
|--------------------|-------------------------------------------------------------------------|
| `wtype`            | Cursor injection is disabled. Clipboard copy still works.               |
| `wl-copy`          | Clipboard copy disabled. Cursor injection still works.                  |
| `pw-play` + `paplay` | Audio feedback disabled; all cue calls become no-ops.                  |
| `pw-play` only     | Fall back to `paplay`.                                                  |
| `input` group / uaccess | **Fatal.** Daemon prints install hint, exits 78.                     |
| Default mic device | **Fatal.** Daemon prints device list, exits 78.                         |
| ASR model          | **Fatal at startup.** Daemon prints `stenographer model download`.     |
| `faster-whisper` Python import | **Fatal.** Daemon prints `pip install` hint, exits 78.       |
| `python-evdev` Python import   | **Fatal.** Daemon prints `pip install` hint, exits 78.       |
| `sounddevice` Python import    | **Fatal.** Daemon prints `pip install` hint, exits 78.       |

Why the asymmetry: a session can still produce value with the clipboard
even without `wtype`, and with the cursor even without `wl-copy`. But
without the input group, the mic, or the ASR stack, there is nothing
left to do.

## Runtime error matrix

| Trigger                                                  | Action                                                                                        |
|----------------------------------------------------------|-----------------------------------------------------------------------------------------------|
| `wtype` exits non-zero on injection                     | Log `output.inject: wtype failed (rc=N, stderr=...)`. Copy to clipboard as fallback.           |
| `wl-copy` exits non-zero on write                       | Log `output.clipboard: wl-copy failed`. Skip. The transcript is still typed.                  |
| `pw-play` / `paplay` exits non-zero on cue              | Log `audio.feedback: cue <name> failed`. Disable feedback for the rest of the session.         |
| faster-whisper `transcribe()` raises                    | Log full traceback. Fire `error` cue. Do NOT inject. Do NOT write to clipboard.               |
| faster-whisper returns empty `text`                     | Log at INFO level. Skip injection and clipboard. (User spoke but nothing was recognized.)      |
| `sounddevice.PortAudioError` mid-recording              | Log. Discard the in-flight utterance. Fire `error` cue. Return to IDLE.                        |
| Hotkey device disappears mid-session (USB unplug)        | Log. Try to re-acquire every 2 s for 30 s, then exit 1.                                      |
| `SIGINT` / `SIGTERM`                                    | Drain in-flight utterance (transcribe + inject + clipboard), then exit 0.                     |
| `SIGPIPE`                                               | Suppress (stderr closed by a launcher).                                                       |
| Uncaught exception in any component                     | Log full traceback. Fire `error` cue. Return to IDLE. Daemon keeps running.                   |

## Logging policy

- v1 uses stdlib `logging` configured by `capabilities.py` at startup.
- Default level: `INFO`. Override with the `STENOGRAPHER_LOG_LEVEL` env
  var (one of `DEBUG`, `INFO`, `WARNING`, `ERROR`).
- Format: `%(asctime)s %(levelname)-7s %(name)s: %(message)s`.
- Destination: stderr. A tee'd file is also written to
  `$XDG_STATE_HOME/stenographer/stenographer.log`
  (default `~/.local/state/stenographer/stenographer.log`) so a
  graphical-session crash is recoverable post-mortem.
- The `error` cue is fired **only** for the rows above that mark it.
  Component code MUST NOT fire it directly; it MUST call
  `errors.notify_failure(reason)` from `stenographer.errors`.

## `stenographer.errors` module API

```python
import logging
from typing import NoReturn

log = logging.getLogger(__name__)

class StenographerError(Exception): ...
class ConfigError(StenographerError): ...     # -> exit 78
class CapabilityError(StenographerError): ... # -> exit 78
class AudioCaptureError(StenographerError): ...
class TranscriptionError(StenographerError): ...

def notify_failure(reason: str) -> None:
    """Fire the error cue (if feedback is available) and log at ERROR."""

def fatal(message: str, code: int = 78) -> NoReturn:
    """Log at CRITICAL and exit with the given code."""

def degrade_capability(name: str) -> None:
    """Mark a capability as unavailable for the rest of the session."""
```

## Test policy

- Unit tests for each component MUST inject a fake `Capabilities` so
  the full degradation matrix is exercised without root or a real
  sound server.
- One integration test (marked `@pytest.mark.integration`) exercises
  the real `wtype` / `wl-copy` / `pw-play` stack on a Wayland session;
  skipped automatically when the required binaries are absent.

## Out of scope (v1)

- Crash-report uploads.
- GUI notifications (libnotify).
- Automatic restart logic for `wtype` / `wl-copy` becoming available
  mid-session.

## Open questions

- Should the daemon write a coredump on uncaught exceptions? v1: no.
- Should the log file be rotated? v1: no (append; user can truncate).
