<!--
SPDX-License-Identifier: GPL-3.0-or-later
-->

# 06 — Clipboard

## Dependencies

- **Reads:** `00-overview.md` (Clipboard Manager definition).
- **Reads:** `07-configuration.md` (`clipboard.*` keys).
- **Reads:** `09-error-handling.md` (capability matrix for `wl-copy`).
- **Reads:** `10-packaging.md` (`wl-copy` / `wl-paste` system deps).
- **Blocks:** `05-text-output.md` calls into this module on fallback.
- **Blocks:** `08-process-model.md` constructs the Clipboard Manager.

## Goal

Specify how the final transcript is written to the Wayland clipboard,
how the daemon detects `wl-copy` / `wl-paste` at startup, and what
behavioural guarantees the rest of the system can rely on.

## Startup probe

`Capabilities.probe()` (see `10-packaging.md`) checks for `wl-copy`
and `wl-paste` on `PATH` using `shutil.which`. The results
`has_wl_copy` and (implicit) `has_wl_paste` are stored on the
`Capabilities` object. If `wl-copy` is missing, `has_wl_copy` is
`False` and the Clipboard Manager degrades to a no-op (see
`09-error-handling.md`); the daemon does NOT exit.

The probe also confirms the Wayland session is live:

```python
import os
wayland_display = os.environ.get("WAYLAND_DISPLAY")
```

If `WAYLAND_DISPLAY` is unset, the daemon logs a warning at startup
("stenographer: WAYLAND_DISPLAY is not set; wl-copy may fail") but
continues — some compositors (KDE) export it lazily.

## API

```python
# stenographer.output.clipboard
import subprocess
from typing import Optional

class ClipboardManager:
    def __init__(self, *, available: bool) -> None: ...

    def copy(self, text: str) -> bool:
        """Copy `text` to the Wayland clipboard. Return True on success."""

    def read(self) -> Optional[str]:
        """Read the current clipboard text via wl-paste. For tests."""

    def close(self) -> None: ...
```

### `copy()`

Implementation:

```python
def copy(self, text: str) -> bool:
    if not self._available:
        return False
    try:
        proc = subprocess.run(
            ["wl-copy"],
            input=text.encode("utf-8"),
            check=True,
            timeout=2.0,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError) as exc:
        log.error("output.clipboard: wl-copy failed: %s", exc)
        return False
```

- The text is fed in on `stdin`; we do NOT pass it as an argv argument.
- MIME type is implicitly `text/plain;charset=utf-8` (wl-copy's default
  when fed UTF-8 bytes). No `-t text/plain` is necessary.
- Timeout is 2.0 s. If the user has a hung wl-copy, we log and move on
  rather than block the next utterance.
- `wl-copy` runs in the foreground and the daemon waits for the data
  to be drained before returning. This is fine: typical transcripts
  are < 5 KB and `wl-copy` accepts them in well under 100 ms.

### `read()`

```python
def read(self) -> Optional[str]:
    if not self._available:
        return None
    try:
        proc = subprocess.run(
            ["wl-paste", "--no-newline"],
            check=True,
            capture_output=True,
            timeout=2.0,
        )
        return proc.stdout.decode("utf-8")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError) as exc:
        log.error("output.clipboard: wl-paste failed: %s", exc)
        return None
```

`--no-newline` strips the trailing newline `wl-paste` adds by
default. `read()` is used by the test suite to verify the copy
contract; the daemon itself never reads from the clipboard.

## Behavioural guarantees

1. **Always copy when `cfg.clipboard.enabled` is `true` AND
   `has_wl_copy` is `true` AND the transcript is non-empty.** No
   opt-out per-utterance.
2. **Copy and inject are independent.** A failure in `wtype` does not
   affect the clipboard copy, and vice versa. Both run, in any order,
   after a successful transcript.
3. **Empty transcript is not copied.** If `Worker` returns an empty
   string, neither injection nor clipboard is performed.
4. **The clipboard write happens once per utterance.** No polling,
   no "keep alive" — once `wl-copy` exits 0, the data is owned by
   the Wayland compositor's clipboard manager.
5. **The daemon does not interact with the primary selection.** Only
   the regular clipboard (`wl-copy` without `--primary`).

## Interaction with the user's existing clipboard manager

The Wayland compositor (or a user-installed clipboard manager like
`clipman` or `copyq`) decides clipboard lifetime. `stenographer` does
nothing special here: it writes once and lets the compositor manage
the data. If the user kills the compositor, the clipboard may be
cleared — that is the compositor's problem, not ours.

## Out of scope (v1)

- The primary selection (`wl-copy --primary`).
- HTML / RTF / image clipboard types.
- Clipboard history (we do not maintain one).
- X11 fallbacks (`xclip`, `xsel`).
- Copy on selection (middle-click).

## Open questions

- Should we add a `clipboard.on_failure` config (e.g. `keep`,
  `clear`, `noop`) so the user can decide what happens if injection
  fails? v1: `noop` (the current behaviour). The user can fix
  injection and re-press the hotkey.
- Should we copy a "stenographer:" prefix to the clipboard so the
  user can tell dictation from manual paste? v1: no.
