<!--
SPDX-License-Identifier: GPL-3.0-or-later
-->

# 05 — Text output

## Dependencies

- **Reads:** `00-overview.md` (Injector definition, glossary).
- **Reads:** `07-configuration.md` (`output.*` keys).
- **Reads:** `09-error-handling.md` (capability matrix for `wtype`,
  runtime error policy, fallback behaviour).
- **Reads:** `10-packaging.md` (`wtype` system dep).
- **Reads:** `06-clipboard.md` (fallback path; this doc depends on
  that one being implemented first).
- **Blocks:** `08-process-model.md` constructs the Injector and
  calls it from the Session.

## Goal

Specify the `Injector` component: how the final transcript reaches
the focused window — either typed at the cursor via `wtype` or pasted
from the clipboard with a simulated Ctrl+V — what the auto-spacing and
length rules are, and the documented fallback to the clipboard when
`wtype` is missing or fails.

## Injection method

`cfg.output.injection_method` (default `"paste"`; see
`07-configuration.md`) selects how the transcript is delivered:

| Method   | Behaviour                                                                 |
|----------|---------------------------------------------------------------------------|
| `"text"` | Type the transcript at the cursor with `wtype`. Segments stream as they are decoded (`type_text(seg.text, raw=True)` per segment; see `03-transcription.md`). |
| `"paste"`| Do not type mid-stream. Play the `segment` cue per decoded segment, then at the end copy the full text to the clipboard (`06-clipboard.md`) and simulate Ctrl+V via `Injector.paste()`. |

`"paste"` is the default because it is near-instant for long
transcripts and avoids per-keystroke timing issues in some apps;
`"text"` gives live streaming feedback but is slower and depends on the
target app honouring synthetic key events.

Both methods require `wtype`. When `wtype` is unavailable, paste mode
degrades to "clipboard populated, no Ctrl+V" — the transcript is on the
clipboard and the user pastes it manually.

## Injection mechanism

`wtype` is the only text-injection path in v1. It implements the
Wayland virtual-keyboard protocol (`zwlr-input-method-protocol-v2`
or the equivalent `zwp-input-method-protocol-unstable-v1` that
`wtype` actually uses). It does NOT require root or the `uinput`
group.

```python
import subprocess
import shlex

class Injector:
    def __init__(self, *, available: bool) -> None: ...

    def type_text(self, text: str, *, raw: bool = False) -> bool:
        """Type `text` at the focused window. Return True on success."""

    def paste(self) -> bool:
        """Simulate Ctrl+V (`wtype -M ctrl v -m ctrl`). Return True on
        success. Used by paste mode after the transcript is on the
        clipboard."""
```

### `type_text()`

```python
def type_text(self, text: str, *, raw: bool = False) -> bool:
    if not self._available:
        log.warning("output.inject: wtype not available; skipping")
        return False
    if not raw:
        text = self._prepare(text)
    if not text:
        return True  # nothing to type
    try:
        proc = subprocess.run(
            ["wtype", "--", text],
            check=True,
            timeout=5.0,
            capture_output=True,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError) as exc:
        log.error(
            "output.inject: wtype failed (rc=%s, stderr=%s); "
            "falling back to clipboard",
            exc.returncode if isinstance(exc, subprocess.CalledProcessError) else -1,
            getattr(exc, "stderr", b"").decode("utf-8", "replace")
            if isinstance(exc, subprocess.CalledProcessError) else "",
        )
        return False
```

The `--` is mandatory so `wtype` treats its argument as positional
text, not a flag. This makes text beginning with `-` safe.

### Timeout

5.0 s. A typical 200-character transcript at default rate is
injected in well under 1 s; 5 s is generous headroom for slower
hardware.

## Text preparation

```python
def _prepare(self, text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    if len(text) > self._max_chars:
        log.warning(
            "output.inject: truncating transcript from %d to %d chars",
            len(text), self._max_chars,
        )
        text = text[: self._max_chars]
    if self._append_trailing_space:
        text += " "
    return text
```

- Leading / trailing whitespace is stripped so dictation does not
  produce stray newlines.
- Length is capped at `cfg.output.max_chars` (default `4096`).
  Truncation is logged at WARNING; the user can re-dictate the
  remainder.
- A single trailing space is appended by default
  (`cfg.output.append_trailing_space = true`) so the next typed
  character is separated. The user can disable this if their target
  application (e.g. a code editor) prefers no trailing space.

## Unicode

`wtype` accepts UTF-8 text. faster-whisper emits UTF-8. The injector
passes the text through unchanged; no transliteration, no
normalization, no emoji conversion.

## Fallback to clipboard

`Injector` does NOT itself write to the clipboard. When
`type_text()` returns `False`, the Session:

1. Logs the failure (already done inside `type_text`).
2. Calls `errors.notify_failure("text injection failed")` so the
   `error` cue fires.
3. The clipboard copy is performed **independently** of injection
   success (see `06-clipboard.md` Behavioural Guarantee 2). It is
   NOT a fallback for injection failure; it always runs.

The reasoning: by the time the user notices that the cursor did
not get the text, the clipboard still has the transcript, so they
can paste it with Ctrl+V. This is a more useful failure mode than
silently swallowing the input.

## What the user sees on failure

| State of the world                  | Cursor           | Clipboard         | Cue      |
|-------------------------------------|------------------|-------------------|----------|
| Both injection and clipboard OK     | transcript typed | transcript copied | none     |
| Injection fails, clipboard OK       | (unchanged)      | transcript copied | `error`  |
| Injection OK, clipboard fails       | transcript typed | (unchanged)       | none     |
| Both fail                           | (unchanged)      | (unchanged)       | `error`  |
| Transcript empty                    | (unchanged)      | (unchanged)       | none     |

The "no injection AND no clipboard" case is the empty-transcript
case (see `03-transcription.md`).

### ``raw`` mode

When ``raw=True``, ``_prepare()`` is bypassed entirely: the text is
sent to ``wtype`` with no strip, no length truncation, and no
trailing-space append.  This is used by the Session for streaming
partial segments so that the model's intra-segment whitespace
(including leading spaces that indicate continuation) is preserved.

## Edge cases

- **Focused window is a Wayland text-input-unaware app.** Some games
  and some Electron apps do not subscribe to the input-method
  protocol. `wtype` silently does nothing in that case. The
  clipboard copy still succeeds. This is documented as a known
  limitation; v1 does not detect it.
- **Focused window is a TTY.** `wtype` works for TTYs. The
  transcript appears at the shell prompt.
- **No focused window (e.g. desktop is showing).** `wtype` either
  silently does nothing or, on some compositors, types into a
  hidden / dev/null surface. The clipboard copy is unaffected.
- **Very long transcript.** Truncated to `cfg.output.max_chars`
  with a WARNING log.

## Out of scope (v1)

- HTML / RTF injection.
- Per-app configuration (e.g. "in a terminal, append a newline
  instead of a space").
- Detect "text-input protocol unsupported" and surface a clearer
  error.
- ydotool / uinput fallback (the spec explicitly chooses `wtype`
  only; see `00-overview.md`).

## Open questions

- Should we send the text in chunks (e.g. 64 chars at a time) to
  reduce the perceived latency of long transcriptions? v1: no;
  `wtype` is fast enough.
- Should the trailing space be omitted when the transcript ends
  with terminal punctuation (`.`, `!`, `?`)? v1: no; the user can
  configure `output.append_trailing_space = false` if they care.
