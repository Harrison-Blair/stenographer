# Native desktop build acceptance

These CI artifacts are development builds, unsigned and unaccepted for release.
They contain the independent `stenographer` and `stenographer-ui` executables.
Automated offscreen startup is not interactive native acceptance.

Windows and macOS provide settings and analytics; dictation and service
integration are unavailable until their native providers are implemented.
Before release, record interactive installation/uninstallation, microphone,
keyboard, clipboard, service behavior, accessibility, light/dark appearance,
scaling, and crash-isolation checks for each supported target. macOS Intel and
Apple Silicon additionally require signing and notarization; Windows requires
installation/signing verification. Do not publish these artifacts as supported
native dictation packages.

Install a development bundle per-user with `install-native.py`; Python 3.12+
is needed for this installer only. Linux normal releases use `install.sh` from
the accompanying source distribution. Headless environments can install the
Python package without its `desktop` extra, or build with
`STENOGRAPHER_BUILD_HEADLESS=1`. Managed backup/restore remains pending.
