# Native build acceptance

These CI artifacts are unsigned development builds, unaccepted for release.
They contain the `stenographer` CLI/daemon and its existing helpers, with no
settings GUI or Qt. Automated CLI startup does not establish native dictation
acceptance.

Windows and macOS provide CLI setup and numeric diagnostics; dictation and
service integration remain unavailable until their native providers are
implemented. Do not publish these artifacts as supported native dictation
packages.

Before release, record real installation/uninstallation, microphone, keyboard,
clipboard, service behavior, and helper crash isolation for each release target.
Verify dictation in hold, toggle, and hybrid modes, including the maximum-duration
cap, and the pill's appearance, spectrum, loading animation, and disappearance.
Inspect daemon and helper logs for numeric diagnostics without transcript or
audio content. Follow all real-machine gates in `AGENTS.md`; automated checks
never access the microphone. macOS Intel and Apple Silicon additionally require
signing and notarization; Windows requires installation/signing verification.

Development bundles are relocatable directories: copy the whole directory and
run its `stenographer` executable (`stenographer.exe` on Windows). There is no
Windows/macOS development installer. Linux normal releases use `install.sh`
from the accompanying source distribution. `--headless` remains accepted by the
Linux build/install/reinstall scripts as a compatibility no-op. Removing the old
GUI preserves configuration, analytics history, models, and logs. Managed
backup/restore remains pending.
