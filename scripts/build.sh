#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Local PyInstaller onedir build. See BUILD.md.
#
# Default output is an indeterminate progress bar driven by the PyInstaller
# log, with a live tail of the last log lines; the full log lands in
# dist/build.log. --verbose streams it instead.
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

.venv/bin/python scripts/sound_asset_guard.py src/stenographer/assets/sounds

if [[ "${VERBOSE}" -eq 1 ]]; then
    .venv/bin/pyinstaller --noconfirm --clean packaging/stenographer.spec
else
    mkdir -p dist
    LOG="dist/build.log"
    : > "${LOG}"

    progress_indeterminate_start "building" "preparing build"
    progress_tail "${LOG}"
    .venv/bin/pyinstaller --noconfirm --clean packaging/stenographer.spec &> "${LOG}" &
    build_pid=$!

    build_phase="preparing build"
    hook_count=0
    hidden_import_count=0
    last_log_line=0

    build_counter() {
        local counter=""
        if ((hook_count > 0)); then
            counter="${hook_count} hooks"
        fi
        if ((hidden_import_count > 0)); then
            [[ -n "${counter}" ]] && counter+=", "
            counter+="${hidden_import_count} hidden"
        fi
        printf '%s' "${counter}"
    }

    # Consume each new log line once. This preserves even very short phase
    # transitions and counts only work PyInstaller has explicitly reported.
    read_build_activity() {
        local current_log_line line
        current_log_line=$(wc -l < "${LOG}")
        ((current_log_line > last_log_line)) || return 0

        while IFS= read -r line; do
            case "${line}" in
                *"Processing "*" hook "*) ((hook_count += 1)) ;;
                *"Analyzing hidden import "*) ((hidden_import_count += 1)) ;;
            esac
            case "${line}" in
                *"Running Analysis "*)
                    build_phase="dependency analysis"
                    progress_activity "${build_phase}" "$(build_counter)"
                    ;;
                *"Processing module hooks (post-graph stage)"*)
                    build_phase="post-graph hooks"
                    progress_activity "${build_phase}" "$(build_counter)"
                    ;;
                *"Building PYZ (ZlibArchive)"*)
                    build_phase="creating PYZ"
                    progress_activity "${build_phase}" "$(build_counter)"
                    ;;
                *"Building PKG (CArchive)"*)
                    build_phase="packaging"
                    progress_activity "${build_phase}" "$(build_counter)"
                    ;;
                *"Building EXE from "*)
                    build_phase="assembling executable"
                    progress_activity "${build_phase}" "$(build_counter)"
                    ;;
                *"Building COLLECT "*)
                    build_phase="collecting bundle"
                    progress_activity "${build_phase}" "$(build_counter)"
                    ;;
            esac
        done < <(sed -n "$((last_log_line + 1)),${current_log_line}p" "${LOG}")
        last_log_line=${current_log_line}
        progress_activity "${build_phase}" "$(build_counter)"
    }

    while kill -0 "${build_pid}" 2>/dev/null; do
        read_build_activity
        progress_tick
        sleep 0.15
    done
    read_build_activity

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
