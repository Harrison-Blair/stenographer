#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Rebuild the current development checkout and replace the locally installed
# standalone binary. Extra arguments are passed to install.sh.
set -euo pipefail

cd "$(dirname "$0")/.."

usage() {
    cat <<EOF
Usage: scripts/reinstall.sh [--no-enable] [--no-start] [--install-dir DIR]

Rebuild the current -dev checkout and replace the locally installed onedir
bundle. The active daemon is stopped only after a successful build, then the
fresh bundle is installed and started.

Options:
  --no-enable    Install the unit but skip enable/start
  --no-start     Install the unit but skip enable/start (implies --no-enable)
  --install-dir  Override the install directory (default ~/.local/share/stenographer)
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi

version=$(
    .venv/bin/python -c \
        "import runpy; print(runpy.run_path('src/stenographer/_version.py')['__version__'])"
)
if [[ "${version}" != *-dev ]]; then
    echo "Refusing to reinstall non-development version ${version}." >&2
    echo "Expected src/stenographer/_version.py to end in -dev." >&2
    exit 1
fi

echo "==> Rebuilding stenographer ${version} from the current checkout ..."
scripts/build.sh
echo

# Installing over an active onedir bundle does not restart the already-mapped
# process. Stop it only after the build succeeds; install.sh starts the fresh
# bundle by default (or leaves it stopped when passed --no-enable/--no-start).
if command -v systemctl >/dev/null 2>&1 \
    && systemctl --user is-active --quiet stenographer.service; then
    echo "==> Stopping the installed development daemon ..."
    systemctl --user stop stenographer.service
    echo
fi

scripts/install.sh "$@"

echo "==> Reinstalled stenographer ${version}."
