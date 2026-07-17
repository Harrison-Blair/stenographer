# FTHR-015 evidence

Human-executed validation. Per the feather's Description this is the test-first
exception: there is no pytest run, and the evidence below is the recorded
observation of the real experiment on real hardware.

Method: `.fledge/scratch/fthr-015-probe.sh shift-insert 10` — populates both the
clipboard (`wl-copy`) and the primary selection (`wl-copy --primary`) with a
fresh random token, counts down, fires `wtype -M shift -k Insert -m shift`, then
records the focused window via `hyprctl activewindow -j` at fire time (so the
target is confirmed, not assumed). A distinct token per run makes a stale
clipboard distinguishable from a fresh paste.

Environment: Hyprland, `XDG_SESSION_TYPE=wayland`, `input:follow_mouse = 1`.
`wtype` 0.4 at `/usr/bin/wtype`; `wl-copy` present; `ydotool` absent.

## AC-1

Per-target observations.

### (a) kitty running Claude Code — PASS

Focused at fire time (`hyprctl activewindow -j`):

```
"class": "kitty",
"title": "✳ Claude Code",
```

Token `fox-4059` appeared at the Claude Code prompt. No unintended side effect:
no `quoted-insert` literal artifact, no visual-block-mode entry, no kitty
`paste_actions` confirm dialog.

Note: kitty's default binding is `map shift+insert paste_from_selection`, i.e.
it pastes the PRIMARY selection, not the clipboard. This target passes
*because* the dual-population design populates primary as well — a
clipboard-only implementation would fail here.

### (b) VSCodium integrated terminal running Claude Code — PASS

Focused at fire time:

```
"class": "codium",
"title": "Claude Code - stenographer - VSCodium",
```

Token `fox-6153` pasted at the Claude Code prompt. No unintended side effect.
Confirms xterm.js inside VSCodium honors Shift+Insert — an unknown the plumage
explicitly refused to assume.

### (c) VSCodium editor pane — PASS

Focused at fire time:

```
"class": "codium",
"title": "● fledge-incubator.md - stenographer - VSCodium",
```

Token `fox-1340` pasted into the editor buffer. No unintended side effect (no
unrelated command or keybind fired).

Caveat on method, recorded for honesty: this run landed in a real tracked repo
file rather than a scratch buffer. The paste was reverted with undo and did not
reach disk — verified afterwards with `git status --short` (file absent from the
modified list) and `grep -rn 'fox-[0-9]\{4\}' .claude/ .fledge/pluma/ src/`
(no matches). The observation itself is unaffected.

## AC-2

```
RESULT: 3/3 PASS — build universal chord (PLM-009 FC-1/FC-2)
```

All three named targets pasted correctly with no unintended side effect.
Per PLM-009's pre-committed binary rule, this selects **Branch 1** for FTHR-016
(dual clipboard+primary population in `ClipboardManager.copy()`; `Injector.paste()`
fires Shift+Insert) and the **per-word delta-firing** branch for FTHR-017
(PLM-010 FC-4/AC-4). The static `output.paste_chord` fallback (PLM-009 FC-5,
FTHR-016 AC-3, FTHR-017 AC-6) is NOT built.

## AC-3

No files under `src/stenographer/` or `tests/` were modified by this feather.
Verified with `git status --short`: the only changes in the tree are the
forager's regenerated `.fledge/nest/*.md` docs and the untracked new spec files
from the planning phase. The probe helper lives at
`.fledge/scratch/fthr-015-probe.sh` (scratch, not `src/`).

## Out-of-scope finding — wtype does not reach XWayland clients

Not required by any AC; recorded because it materially affects PLM-009's ydotool
question and was discovered during this feather.

An accidental first run fired into Discord and nothing pasted. A control run with
`ctrl-v` (`.fledge/scratch/fthr-015-probe.sh ctrl-v 10`) also produced nothing —
so the failure is **not** chord-related. `hyprctl clients -j` explains why:

```
discord    xwayland=True     <- both chords fail
Spotify    xwayland=True
codium     xwayland=False    <- targets (b), (c): pass
kitty      xwayland=False    <- target (a): pass
firefox    xwayland=False
```

wtype uses the Wayland virtual-keyboard protocol, which does not surface to
XWayland clients. **No chord will ever work in an XWayland app via wtype** — this
is a delivery failure, not a chord failure, and it is the mechanism behind the
user's original "doesn't work on x11 apps" complaint.

Consequence for the plan: all three of FTHR-015's targets are native Wayland, so
this 3/3 PASS validates the universal chord **only for native-Wayland clients**.
It says nothing about XWayland apps (Discord, Spotify), where wtype cannot
deliver at all. PLM-009 scoped the ydotool pivot as conditional on chord
validation failing; this finding shows the real trigger is different — XWayland
support, if wanted, requires ydotool (kernel uinput) regardless of chord, and
`ydotool` is not currently installed. Whether XWayland coverage is in scope is a
user decision that has not been taken.
