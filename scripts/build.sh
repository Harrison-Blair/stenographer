#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Local PyInstaller onedir build. See docs/building.md.
#
# Default output is an indeterminate progress bar driven by the PyInstaller
# log, with a live tail of the last log lines; the full log lands in
# dist/build.log. --verbose streams it instead.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/progress.sh
source scripts/progress.sh

VERBOSE=0
for build_option in "$@"; do
    case "${build_option}" in
        --verbose) VERBOSE=1 ;;
        --headless) : ;; # Compatibility: all builds now contain only the CLI/daemon.
        *) echo "error: unknown build option: ${build_option}" >&2; exit 64 ;;
    esac
done

if [ ! -x .venv/bin/pyinstaller ]; then
    echo "error: .venv/bin/pyinstaller not found — run: .venv/bin/pip install -e '.[dev,build]'" >&2
    exit 1
fi

.venv/bin/python scripts/sound_asset_guard.py src/stenographer/assets/sounds
# The speaker model is pinned by size and sha256 and kept between builds.
.venv/bin/python -I scripts/fetch_speaker_model.py

if [[ "${VERBOSE}" -eq 1 ]]; then
    .venv/bin/pyinstaller --noconfirm --clean packaging/stenographer.spec
else
    mkdir -p dist
    LOG="dist/build.log"
    : > "${LOG}"

    progress_indeterminate_start "building" "preparing build"
    progress_tail "${LOG}"
    if ! run_logged .venv/bin/pyinstaller --noconfirm --clean packaging/stenographer.spec; then
        progress_fail
        echo
        tail -n 20 "${LOG}"
        echo
        echo "error: pyinstaller failed — full log: ${LOG}" >&2
        exit 1
    fi
    progress_done
fi

echo "built: dist/stenographer/stenographer"
.venv/bin/python scripts/sound_asset_guard.py \
    dist/stenographer/_internal/stenographer/assets/sounds
dist/stenographer/stenographer --version
for completion_shell in bash zsh fish; do
    completion_output=$(dist/stenographer/stenographer completion "${completion_shell}")
    if [[ -z "${completion_output}" ]]; then
        echo "error: frozen ${completion_shell} completion is empty" >&2
        exit 1
    fi
done
