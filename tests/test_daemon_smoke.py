# SPDX-License-Identifier: GPL-3.0-or-later
"""Integration smoke + manual acceptance procedure for the daemon (M5 Verify).

The M5 Verify clause — "real dictation end-to-end on both compositor families" —
is the acceptance test and is inherently MANUAL: it needs a microphone, real
speech, and a focused window. It cannot be asserted programmatically. Run it by
hand, once on EACH compositor family:

    MANUAL ACCEPTANCE PROCEDURE
    1. Ensure the model is cached (`stenographer model download`) and you are
       in the `input` group with write access to /dev/uinput.
    2. Start the daemon:  `stenographer run`   (or the systemd user unit).
    3. Focus a text field in any application (a terminal, an editor, a browser).
    4. Press and HOLD the hotkey (default KEY_RIGHTALT), speak a short sentence,
       then RELEASE the key.
    5. Confirm: the record_start cue played on press, record_stop on release,
       and after a moment the transcribed sentence is PASTED at the cursor with
       the delivered cue. The same text is on the clipboard (`wl-paste`).
    6. Repeat on a Hyprland (wlroots) session AND on a GNOME Wayland (Mutter)
       session. Both must deliver the text at the cursor — that is the merge gate.

The only part that is honest to automate is the single-instance lock: a second
acquire against the process's ACTUAL lock path must fail while the first is held.
Self-skips unless STENOGRAPHER_INTEGRATION=1.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration

if os.environ.get("STENOGRAPHER_INTEGRATION") != "1":
    pytest.skip("integration suite requires STENOGRAPHER_INTEGRATION=1", allow_module_level=True)

from stenographer.daemon import (  # noqa: E402
    LOCK_PATH,
    acquire_single_instance_lock,
    release_single_instance_lock,
)


def test_real_lock_path_mutual_exclusion():
    fd = acquire_single_instance_lock()
    if fd < 0:
        pytest.skip(f"another instance already holds {LOCK_PATH}")
    try:
        # A real, non-mocked second acquire against the daemon's actual runtime
        # lock path fails while the first fd holds it.
        assert acquire_single_instance_lock() == -1
    finally:
        os.close(fd)
        release_single_instance_lock()
