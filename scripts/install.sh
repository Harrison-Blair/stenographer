#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Install stenographer for the current user: build the onedir bundle (if
# needed), copy it to ~/.local/share/stenographer/, symlink the launcher
# into ~/.local/bin/, and install + enable the systemd user unit.
#
# Default output is an indeterminate progress bar with a live tail of the last
# log lines; tool output lands in dist/install.log. --verbose streams everything
# instead.
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck source=scripts/progress.sh
source scripts/progress.sh

BIN_DIR="${HOME}/.local/bin"
INSTALL_DIR="${HOME}/.local/share/stenographer"
SERVICE_SRC="packaging/stenographer.service"
SERVICE_DST="${HOME}/.config/systemd/user/stenographer.service"
DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
BASH_COMPLETION_DST="${DATA_HOME}/bash-completion/completions/stenographer"
ZSH_COMPLETION_DST="${DATA_HOME}/zsh/site-functions/_stenographer"
FISH_COMPLETION_DST="${DATA_HOME}/fish/vendor_completions.d/stenographer.fish"
DO_ENABLE=1
DO_START=1
VERBOSE=0

usage() {
    cat <<EOF
Usage: $(basename "$0") [--no-enable] [--no-start] [--install-dir DIR] [--verbose]

Install stenographer from the local build tree:
  1. Build the onedir bundle (if not already built)
  2. Copy dist/stenographer/ to INSTALL_DIR (default ~/.local/share/stenographer/)
  3. Symlink the launcher into ~/.local/bin/stenographer
  4. Cache Bash, Zsh, and Fish completion definitions under XDG_DATA_HOME
  5. Install the systemd user unit
  6. Enable and start the service (unless told not to)

Options:
  --no-enable    Install the unit but do not enable or start it
  --no-start     Enable the unit but do not start it now
  --install-dir  Override install directory (default ~/.local/share/stenographer)
  --verbose      Stream full tool output instead of the progress bar
EOF
    exit 64
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-enable) DO_ENABLE=0; DO_START=0 ;;
        --no-start)  DO_START=0 ;;
        --install-dir)
            shift
            [[ $# -gt 0 ]] || { echo "--install-dir requires an argument"; usage; }
            INSTALL_DIR="$1"
            ;;
        --verbose) VERBOSE=1 ;;
        --help|-h) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
    shift
done

BINARY_PATH="${INSTALL_DIR}/stenographer"
SYMLINK_PATH="${BIN_DIR}/stenographer"
LOG="dist/install.log"
NOTES=()

# step "label" — update the current phase (or print a banner in verbose mode).
step() {
    if [[ "${VERBOSE}" -eq 1 ]]; then
        echo "==> $1 ..."
    else
        progress_activity "$1" ""
    fi
}

# run_logged CMD... — run a command, hiding its output in $LOG unless verbose.
# Quiet mode backgrounds the command and redraws while it waits so the log
# tail beneath the bar stays live; wait recovers the real exit status.
run_logged() {
    if [[ "${VERBOSE}" -eq 1 ]]; then
        "$@"
    else
        "$@" &>> "${LOG}" &
        local pid=$!
        while kill -0 "${pid}" 2>/dev/null; do
            progress_tick
            sleep 0.15
        done
        wait "${pid}"
    fi
}

install_completion() {
    local shell=$1 destination=$2 temporary
    temporary="${destination}.tmp.$$"
    mkdir -p "$(dirname "${destination}")"
    if ! "${BINARY_PATH}" completion "${shell}" > "${temporary}"; then
        rm -f "${temporary}"
        return 1
    fi
    chmod 0644 "${temporary}"
    mv "${temporary}" "${destination}"
}

# ────────────────────────────────────────────────────────────────
# Step 1 — Build the onedir bundle if needed (before the install
# bar starts, so the build bar and install bar never interleave)
# ────────────────────────────────────────────────────────────────
if [[ ! -x "dist/stenographer/stenographer" ]]; then
    if [[ "${VERBOSE}" -eq 1 ]]; then
        scripts/build.sh --verbose
    else
        scripts/build.sh
    fi
    echo
fi

mkdir -p dist
: > "${LOG}"
if [[ "${VERBOSE}" -ne 1 ]]; then
    progress_indeterminate_start "installing" "preparing install"
    progress_tail "${LOG}"
fi

# ────────────────────────────────────────────────────────────────
# Step 2 — Stop a running service before replacing its files
# ────────────────────────────────────────────────────────────────
# Overwriting an active onedir bundle does not restart the mapped process,
# and the frozen worker child re-execs the launcher path — so the daemon
# must be stopped before the copy.
WAS_ACTIVE=0
if systemctl --user is-active --quiet stenographer.service 2>/dev/null; then
    step "stopping service"
    run_logged systemctl --user stop stenographer.service
    WAS_ACTIVE=1
fi

# ────────────────────────────────────────────────────────────────
# Step 3 — Install the bundle
# ────────────────────────────────────────────────────────────────
step "copying bundle"
mkdir -p "${INSTALL_DIR}"
rm -rf "${INSTALL_DIR:?}"/*
run_logged cp -a dist/stenographer/. "${INSTALL_DIR}/"

step "linking launcher"
mkdir -p "${BIN_DIR}"
if [[ -e "${SYMLINK_PATH}" && ! -L "${SYMLINK_PATH}" ]]; then
    NOTES+=("WARNING: ${SYMLINK_PATH} exists and is not a symlink — leaving it alone.")
else
    ln -sfn "${BINARY_PATH}" "${SYMLINK_PATH}"
fi

# ────────────────────────────────────────────────────────────────
# Step 4 — Cache native shell completions
# ────────────────────────────────────────────────────────────────
step "installing shell completions"
run_logged install_completion bash "${BASH_COMPLETION_DST}"
run_logged install_completion zsh "${ZSH_COMPLETION_DST}"
run_logged install_completion fish "${FISH_COMPLETION_DST}"

# ────────────────────────────────────────────────────────────────
# Step 5 — Install the systemd user unit
# ────────────────────────────────────────────────────────────────
step "installing unit"

# The checked-in unit assumes the default install dir. For a custom
# --install-dir, rewrite ExecStart: %h-relative when under HOME (systemd
# expands %h), absolute otherwise.
if [[ "${INSTALL_DIR}" == "${HOME}"/* ]]; then
    exec_start="%h/${INSTALL_DIR#"${HOME}/"}/stenographer run"
else
    exec_start="${BINARY_PATH} run"
fi
unit_content=$(sed "s|^ExecStart=.*|ExecStart=${exec_start}|" "${SERVICE_SRC}")

mkdir -p "$(dirname "${SERVICE_DST}")"
if [[ -f "${SERVICE_DST}" ]] && [[ "$(cat "${SERVICE_DST}")" == "${unit_content}" ]]; then
    : # unchanged
else
    if [[ -f "${SERVICE_DST}" ]]; then
        mv "${SERVICE_DST}" "${SERVICE_DST}.bak"
        NOTES+=("Backed up existing unit to ${SERVICE_DST}.bak")
    fi
    printf '%s\n' "${unit_content}" > "${SERVICE_DST}"
fi

# ────────────────────────────────────────────────────────────────
# Step 6 — Reload, enable, start
# ────────────────────────────────────────────────────────────────
step "reloading systemd"
run_logged systemctl --user daemon-reload

if [[ "${DO_ENABLE}" -eq 1 ]]; then
    step "enabling service"
    run_logged systemctl --user enable stenographer.service
else
    NOTES+=("Not enabled (--no-enable). Run manually: systemctl --user enable --now stenographer.service")
fi

if [[ "${DO_START}" -eq 1 ]]; then
    step "starting service"
    if ! run_logged systemctl --user start stenographer.service; then
        if [[ "${VERBOSE}" -eq 1 ]]; then
            echo
        else
            progress_fail
            echo
            tail -n 20 "${LOG}"
            echo
        fi
        echo "    Service failed to start. Common causes:"
        echo "      - model not downloaded:  ${SYMLINK_PATH} model download"
        echo "      - missing capability:    ${SYMLINK_PATH} doctor"
        echo "      - logs:                  journalctl --user -u stenographer -f"
        exit 1
    fi
elif [[ "${WAS_ACTIVE}" -eq 1 ]]; then
    NOTES+=("Not restarting the previously running service (--no-start given).")
fi

[[ "${VERBOSE}" -eq 1 ]] || progress_done
echo

# ────────────────────────────────────────────────────────────────
# Post-install checks
# ────────────────────────────────────────────────────────────────
if [[ ${#NOTES[@]} -gt 0 ]]; then
    printf '%s\n' "${NOTES[@]}"
    echo
fi

if [[ ":$PATH:" != *":${BIN_DIR}:"* ]]; then
    echo "WARNING: ${BIN_DIR} is not in your PATH."
    echo "  For the current session: export PATH=\"${BIN_DIR}:\$PATH\""
    echo
fi

echo "Done."
echo "  bundle:   ${INSTALL_DIR}/"
echo "  launcher: ${SYMLINK_PATH}"
echo "  unit:     ${SERVICE_DST}"
echo "  status:   systemctl --user status stenographer.service"
echo
echo "Zsh completion setup (one time): add these lines to ~/.zshrc, then open a new shell:"
echo "  fpath=(\"${DATA_HOME}/zsh/site-functions\" \$fpath)"
echo "  autoload -Uz compinit && compinit"
