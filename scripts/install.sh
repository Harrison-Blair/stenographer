#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Install stenographer: build (if needed), install the standalone binary
# to ~/.local/share/stenographer/, symlink into ~/.local/bin/, and set up
# the systemd user unit.
set -euo pipefail

cd "$(dirname "$0")/.."

BIN_DIR="${HOME}/.local/bin"
INSTALL_DIR="${HOME}/.local/share/stenographer"
SERVICE_DST="${HOME}/.config/systemd/user/stenographer.service"
DO_ENABLE=1
DO_START=1

usage() {
    cat <<EOF
Usage: $(basename "$0") [--no-enable] [--no-start] [--install-dir DIR]

Install stenographer from the local build tree:
  1. Build the standalone binary (if not already built)
  2. Copy dist/stenographer/ to INSTALL_DIR (default ~/.local/share/stenographer/)
  3. Symlink the launcher into ~/.local/bin/stenographer
  4. Install bash completion to ~/.local/share/bash-completion/completions/
  5. Install and (optionally) enable+start the systemd user unit

Options:
  --no-enable    Install unit but do not enable it
  --no-start     Install unit but do not start it (implies --no-enable)
  --install-dir  Override install directory (default ~/.local/share/stenographer)
EOF
    exit 64
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-enable) DO_ENABLE=0 ;;
        --no-start)  DO_ENABLE=0; DO_START=0 ;;
        --install-dir)
            shift
            INSTALL_DIR="$1"
            ;;
        --help|-h) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
    shift
done

BINARY_PATH="${INSTALL_DIR}/stenographer"
SYMLINK_PATH="${BIN_DIR}/stenographer"

# ────────────────────────────────────────────────────────────────
# Step 1 — Build the standalone binary if needed
# ────────────────────────────────────────────────────────────────
if [[ ! -x "dist/stenographer/stenographer" ]]; then
    echo "==> Building standalone binary ..."
    scripts/build.sh
    echo
fi

# ────────────────────────────────────────────────────────────────
# Step 2 — Install the binary
# ────────────────────────────────────────────────────────────────
echo "==> Installing binary to ${INSTALL_DIR}/ ..."
mkdir -p "${INSTALL_DIR}"
echo "    Removing the previous bundle ..."
rm -rf "${INSTALL_DIR}"/*
echo "    Copying the new bundle from dist/stenographer/ ..."
cp -a dist/stenographer/* "${INSTALL_DIR}/"
echo "    Bundle copy complete."

echo "    Binary: ${BINARY_PATH}"

# Symlink into ~/.local/bin/
mkdir -p "${BIN_DIR}"
if [[ -L "${SYMLINK_PATH}" ]]; then
    current_target=$(readlink "${SYMLINK_PATH}")
    if [[ "${current_target}" != "${BINARY_PATH}" ]]; then
        echo "    Replacing symlink: ${SYMLINK_PATH} -> ${current_target}"
        rm "${SYMLINK_PATH}"
        ln -s "${BINARY_PATH}" "${SYMLINK_PATH}"
    else
        echo "    Symlink already exists: ${SYMLINK_PATH}"
    fi
elif [[ -e "${SYMLINK_PATH}" ]]; then
    echo "    WARNING: ${SYMLINK_PATH} exists and is not a symlink — skipping"
else
    ln -s "${BINARY_PATH}" "${SYMLINK_PATH}"
    echo "    Symlink: ${SYMLINK_PATH}"
fi
echo

# ────────────────────────────────────────────────────────────────
# Step 3 — Install bash completion
# ────────────────────────────────────────────────────────────────
COMPLETION_DST="${XDG_DATA_HOME:-$HOME/.local/share}/bash-completion/completions/stenographer"
echo "==> Installing bash completion to ${COMPLETION_DST} ..."
mkdir -p "$(dirname "${COMPLETION_DST}")"
cp packaging/stenographer-completion.bash "${COMPLETION_DST}"
echo

# ────────────────────────────────────────────────────────────────
# Step 4 — Install systemd user unit
# ────────────────────────────────────────────────────────────────
echo "==> Installing systemd user unit to ${SERVICE_DST} ..."

# Build the unit content: replace %h/.local/bin/stenographer with the
# actual binary path (using %h as prefix since systemd expands it).
# If the install dir is under HOME, use %h; otherwise use absolute path.
if [[ "${INSTALL_DIR}" == "${HOME}"* ]]; then
    exec_start="%h/${INSTALL_DIR#"${HOME}/"}/stenographer run"
else
    exec_start="${BINARY_PATH} run"
fi

unit_content="[Unit]
Description=stenographer dictation daemon
After=graphical-session.target pipewire.service pulseaudio.service
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=${exec_start}
Restart=on-failure
RestartSec=2

[Install]
WantedBy=graphical-session.target
"

mkdir -p "$(dirname "${SERVICE_DST}")"

if [[ -f "${SERVICE_DST}" ]]; then
    existing_content=$(cat "${SERVICE_DST}")
    if [[ "${existing_content}" == "${unit_content}" ]]; then
        echo "    Unit unchanged, skipping."
    else
        mv "${SERVICE_DST}" "${SERVICE_DST}.bak"
        echo "    Backed up existing unit to ${SERVICE_DST}.bak"
        printf '%s' "${unit_content}" > "${SERVICE_DST}"
        echo "    Unit installed (overwritten)."
    fi
else
    printf '%s' "${unit_content}" > "${SERVICE_DST}"
    echo "    Unit installed."
fi
echo

# ────────────────────────────────────────────────────────────────
# Step 5 — Reload systemd
# ────────────────────────────────────────────────────────────────
echo "==> Reloading systemd user units ..."
systemctl --user daemon-reload
echo

# ────────────────────────────────────────────────────────────────
# Step 6 — Enable and start
# ────────────────────────────────────────────────────────────────
if [[ "${DO_ENABLE}" -eq 1 ]]; then
    echo "==> Enabling and starting stenographer.service ..."
    systemctl --user enable --now stenographer.service
    echo
else
    echo "==> Skipping enable/start (--no-enable given)."
    echo "    Run manually: systemctl --user enable --now stenographer.service"
    echo
fi

# ────────────────────────────────────────────────────────────────
# Post-install checks
# ────────────────────────────────────────────────────────────────
if [[ ":$PATH:" != *":${BIN_DIR}:"* ]]; then
    echo "WARNING: ${BIN_DIR} is not in your PATH."
    echo "  To add it permanently, run one of:"
    echo "    echo 'export PATH=\"${BIN_DIR}:\$PATH\"' >> ~/.bashrc   # bash"
    echo "    echo 'export PATH=\"${BIN_DIR}:\$PATH\"' >> ~/.zshrc    # zsh"
    echo "    fish_add_path \"${BIN_DIR}\"                            # fish"
    echo "  Or for the current session: export PATH=\"${BIN_DIR}:\$PATH\""
    echo
fi
