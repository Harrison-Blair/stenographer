#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Local PyInstaller onedir build. See BUILD.md.
#
# Default output is a progress bar (milestones parsed from the PyInstaller
# log); the full log lands in dist/build.log. --verbose streams it instead.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/progress.sh
source scripts/progress.sh

VERBOSE=0
[[ "${1-}" == "--verbose" ]] && VERBOSE=1

if [ ! -x .venv/bin/pyinstaller ]; then
    echo "error: .venv/bin/pyinstaller not found — run: .venv/bin/pip install -e '.[dev,build]'" >&2
    exit 1
fi

if [[ "${VERBOSE}" -eq 1 ]]; then
    .venv/bin/pyinstaller --noconfirm --clean packaging/stenographer.spec
else
    mkdir -p dist
    LOG="dist/build.log"
    : > "${LOG}"

    progress_start "building"
    .venv/bin/pyinstaller --noconfirm --clean packaging/stenographer.spec &> "${LOG}" &
    build_pid=$!

    # Map the newest recognizable log phase to a checkpoint; redraw every
    # second so elapsed time keeps ticking through quiet stretches.
    while kill -0 "${build_pid}" 2>/dev/null; do
        phase=$(grep -oE 'Running Analysis|Processing module hooks|Building PYZ|Building PKG|Building EXE|Building COLLECT' \
            "${LOG}" 2>/dev/null | tail -n1 || true)
        case "${phase}" in
            "Running Analysis")          progress_update 10 "analyzing imports" ;;
            "Processing module hooks")   progress_update 25 "module hooks" ;;
            "Building PYZ")         progress_update 60 "building PYZ" ;;
            "Building PKG")         progress_update 70 "building PKG" ;;
            "Building EXE")         progress_update 85 "building EXE" ;;
            "Building COLLECT")     progress_update 95 "collecting bundle" ;;
            *)                      progress_tick ;;
        esac
        sleep 1
    done

    if ! wait "${build_pid}"; then
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
dist/stenographer/stenographer --version
