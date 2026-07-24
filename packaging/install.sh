#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# stenographer release installer.
#
# Downloads the latest prebuilt binary from GitHub Releases, verifies its
# SHA-256, installs it, sets up the systemd user unit, and walks you through
# a minimal configuration.
#
# Usage:
#   curl -fsSL https://github.com/Harrison-Blair/stenographer/releases/latest/download/install.sh | bash
#   ./install.sh [--version X.Y.Z] [--yes] [--no-deps]
#
# Environment overrides:
#   STENOGRAPHER_REPO     owner/repo to install from (default Harrison-Blair/stenographer)
#   STENOGRAPHER_VERSION  version to install (default: latest release)
set -euo pipefail

REPO="${STENOGRAPHER_REPO:-Harrison-Blair/stenographer}"
VERSION="${STENOGRAPHER_VERSION:-}"
INSTALL_DIR="${HOME}/.local/share/stenographer"
BIN_DIR="${HOME}/.local/bin"
SYMLINK="${BIN_DIR}/stenographer"
ASSUME_YES=""
DO_DEPS=1

# ── prompt plumbing ─────────────────────────────────────────────────────
# When run via `curl … | bash`, stdin is the script itself, so prompts must
# read from the terminal directly.
if [[ -r /dev/tty ]]; then TTY=/dev/tty; else TTY=""; fi

c_bold=$'\033[1m'; c_red=$'\033[31m'; c_yellow=$'\033[33m'; c_green=$'\033[32m'; c_reset=$'\033[0m'
[[ -t 1 ]] || { c_bold=""; c_red=""; c_yellow=""; c_green=""; c_reset=""; }

info() { printf '%s==>%s %s\n' "$c_bold" "$c_reset" "$*"; }
warn() { printf '%sWARNING:%s %s\n' "$c_yellow" "$c_reset" "$*" >&2; }
err()  { printf '%sERROR:%s %s\n' "$c_red" "$c_reset" "$*" >&2; exit 1; }
ok()   { printf '%s  ✓%s %s\n' "$c_green" "$c_reset" "$*"; }

# ask_yn "prompt" DEFAULT(Y|N) → returns 0 for yes
ask_yn() {
    local prompt="$1" default="${2:-N}" ans hint
    [[ "$default" == "Y" ]] && hint="[Y/n]" || hint="[y/N]"
    if [[ -n "$ASSUME_YES" ]]; then return 0; fi
    if [[ -z "$TTY" ]]; then [[ "$default" == "Y" ]]; return; fi
    read -r -p "$prompt $hint " ans < "$TTY" || ans=""
    ans="${ans:-$default}"
    [[ "$ans" =~ ^[Yy] ]]
}

# ask_default "prompt" "default" → echoes the answer (default if empty/no tty)
ask_default() {
    local prompt="$1" default="$2" ans
    if [[ -z "$TTY" || -n "$ASSUME_YES" ]]; then printf '%s' "$default"; return; fi
    read -r -p "$prompt [$default] " ans < "$TTY" || ans=""
    printf '%s' "${ans:-$default}"
}

fetch() {  # fetch URL OUTFILE
    if command -v curl >/dev/null 2>&1; then
        curl --fail --location --show-error --progress-bar --output "$2" "$1"
    elif command -v wget >/dev/null 2>&1; then
        wget --progress=bar:force:noscroll --output-document="$2" "$1"
    else
        err "need curl or wget to download files"
    fi
}

fetch_stdout() {  # fetch URL → stdout
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$1"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- "$1"
    else
        err "need curl or wget to download files"
    fi
}

# ── argument parsing ────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --version) shift; VERSION="${1#v}" ;;
        --yes|-y)  ASSUME_YES=1 ;;
        --no-deps) DO_DEPS=0 ;;
        --help|-h)
            sed -n '3,16p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) err "unknown option: $1" ;;
    esac
    shift
done

# ── preflight ───────────────────────────────────────────────────────────
info "stenographer installer"
[[ "$(uname -s)" == "Linux" ]] || err "stenographer is Linux-only (detected $(uname -s))."
for tool in tar sha256sum; do
    command -v "$tool" >/dev/null 2>&1 || err "required tool not found: $tool"
done
if [[ -z "${WAYLAND_DISPLAY:-}" && "${XDG_SESSION_TYPE:-}" != "wayland" ]]; then
    warn "no Wayland session detected; stenographer only works under Wayland."
fi

# ── step 1: system dependencies ─────────────────────────────────────────
detect_deps() {  # sets PM_INSTALL and DEPS
    if command -v apt-get >/dev/null 2>&1; then
        PM_INSTALL="sudo apt-get update && sudo apt-get install -y"
        DEPS="wtype wl-clipboard pipewire-audio libevdev1 libportaudio2 libnotify-bin libgtk-4-1 libgtk4-layer-shell0 gir1.2-freedesktop gir1.2-gtk4layershell-1.0"
    elif command -v dnf >/dev/null 2>&1; then
        PM_INSTALL="sudo dnf install -y"
        DEPS="wtype wl-clipboard pipewire-utils libevdev portaudio libnotify gobject-introspection gtk4 gtk4-layer-shell"
    elif command -v pacman >/dev/null 2>&1; then
        PM_INSTALL="sudo pacman -S --needed"
        DEPS="wtype wl-clipboard pipewire libevdev portaudio libnotify gobject-introspection-runtime gtk4 gtk4-layer-shell"
    else
        PM_INSTALL=""
        DEPS="wtype wl-clipboard pipewire libevdev libportaudio libnotify GTK4 gtk4-layer-shell"
    fi
}

install_deps() {
    detect_deps
    local missing=()
    command -v wtype       >/dev/null 2>&1 || missing+=("wtype")
    command -v wl-copy     >/dev/null 2>&1 || missing+=("wl-copy")
    command -v pw-play     >/dev/null 2>&1 || command -v paplay >/dev/null 2>&1 || missing+=("pw-play/paplay")
    command -v notify-send >/dev/null 2>&1 || missing+=("notify-send")
    ldconfig -p 2>/dev/null | grep -q libgtk4-layer-shell || missing+=("gtk4-layer-shell")

    if [[ ${#missing[@]} -eq 0 ]]; then
        ok "core CLIs and GTK4 layer shell present"
    else
        warn "missing: ${missing[*]}"
    fi

    if [[ -z "$PM_INSTALL" ]]; then
        warn "unrecognized package manager; install these manually: $DEPS"
        return
    fi

    local default="N"; [[ ${#missing[@]} -gt 0 ]] && default="Y"
    info "System packages: $DEPS"
    printf '    via: %s %s\n' "$PM_INSTALL" "$DEPS"
    if ask_yn "Install/verify system dependencies now?" "$default"; then
        # shellcheck disable=SC2086
        eval "$PM_INSTALL $DEPS"
        ok "system dependencies installed"
    else
        warn "skipped system dependencies; the daemon may not work until they are installed."
    fi
}

# ── step 2: input group ─────────────────────────────────────────────────
RELOGIN_NEEDED=0
setup_input_group() {
    if id -nG "$USER" 2>/dev/null | tr ' ' '\n' | grep -qx input; then
        ok "user '$USER' is in the 'input' group"
        return
    fi
    warn "user '$USER' is not in the 'input' group (needed to read the hotkey)."
    if ask_yn "Add $USER to the 'input' group with sudo?" "Y"; then
        sudo usermod -aG input "$USER"
        RELOGIN_NEEDED=1
        ok "added to 'input' group — you must log out and back in for this to take effect"
    else
        warn "skipped; the hotkey will not work until you join the 'input' group."
    fi
}

# ── step 3: download + verify + install binary ──────────────────────────
resolve_version() {
    if [[ -n "$VERSION" ]]; then return; fi
    info "Resolving latest release ..."
    local tag
    tag=$(fetch_stdout "https://api.github.com/repos/${REPO}/releases/latest" \
        | grep -m1 '"tag_name"' \
        | sed -E 's/.*"tag_name"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/') || true
    [[ -n "$tag" ]] || err "could not resolve the latest release; pass --version X.Y.Z"
    VERSION="${tag#v}"
}

install_binary() {
    resolve_version
    local base="https://github.com/${REPO}/releases/download/v${VERSION}"
    local tarball="stenographer-${VERSION}-linux-x86_64.tar.gz"
    local shafile="stenographer-${VERSION}-linux-x86_64.sha256"
    local tmp; tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' RETURN

    info "Downloading stenographer v${VERSION} binary archive ..."
    printf '    %s\n' "${base}/${tarball}"
    fetch "${base}/${tarball}" "${tmp}/${tarball}"
    ok "binary archive downloaded"

    info "Downloading SHA-256 checksum ..."
    fetch "${base}/${shafile}" "${tmp}/${shafile}"
    ok "checksum downloaded"

    info "Verifying SHA-256 ..."
    ( cd "$tmp" && sha256sum -c "$shafile" >/dev/null ) \
        || err "SHA-256 verification failed — refusing to install."
    ok "checksum verified"

    info "Extracting release archive ..."
    tar -C "$tmp" -xzf "${tmp}/${tarball}"
    [[ -x "${tmp}/stenographer/stenographer" ]] \
        || err "extracted bundle is missing the launcher."
    ok "release archive extracted"

    info "Installing files to ${INSTALL_DIR} ..."
    mkdir -p "$INSTALL_DIR"
    printf '    Removing the previous bundle ...\n'
    rm -rf "${INSTALL_DIR:?}"/*
    printf '    Copying the new bundle ...\n'
    cp -a "${tmp}/stenographer/." "$INSTALL_DIR/"
    ok "bundle files installed"

    mkdir -p "$BIN_DIR"
    ln -sfn "${INSTALL_DIR}/stenographer" "$SYMLINK"
    ok "installed launcher: ${SYMLINK} -> ${INSTALL_DIR}/stenographer"

    # Make the launcher available for the rest of this script.
    STENO="${INSTALL_DIR}/stenographer"
    ok "$("$STENO" --version)"

    if [[ ":$PATH:" != *":${BIN_DIR}:"* ]]; then
        warn "${BIN_DIR} is not on your PATH. Add it with:"
        printf '      echo '\''export PATH="%s:$PATH"'\'' >> ~/.bashrc\n' "$BIN_DIR"
    fi
}

# ── ASR model choices (mirrors `stenographer bench` defaults) ───────────
# Each entry: "<hf repo id>|<approx download size>|<one-line description>".
# The first entry is the recommended default.
MODEL_CHOICES=(
    "Systran/faster-whisper-medium.en|~1.5 GB|English-only, default with hotword support"
    "Systran/faster-distil-whisper-medium.en|~800 MB|English-only, recommended balance of speed and accuracy"
    "Systran/faster-distil-whisper-small.en|~350 MB|English-only, smallest and fastest"
    "Systran/faster-whisper-large-v3|~3 GB|multilingual, most accurate but slower"
)

# model_size REPO → echoes the size string for a known repo (empty if unknown)
model_size() {
    local repo size _rest
    for entry in "${MODEL_CHOICES[@]}"; do
        IFS='|' read -r repo size _rest <<< "$entry"
        [[ "$repo" == "$1" ]] && { printf '%s' "$size"; return; }
    done
}

# config_model → echoes asr.model from the config (falls back to the default)
config_model() {
    local m=""
    [[ -f "$CONFIG_PATH" ]] && m=$(grep -m1 -E '^asr\.model = ' "$CONFIG_PATH" \
        | sed -E 's/^asr\.model = "?([^"]*)"?.*/\1/')
    printf '%s' "${m:-${MODEL_CHOICES[0]%%|*}}"
}

# pick_model → echoes the chosen repo id (default: first/recommended choice)
pick_model() {
    if [[ -z "$TTY" || -n "$ASSUME_YES" ]]; then
        printf '%s' "${MODEL_CHOICES[0]%%|*}"; return
    fi
    info "Choose the ASR model to download:" >&2
    local i=1 repo size desc
    for entry in "${MODEL_CHOICES[@]}"; do
        IFS='|' read -r repo size desc <<< "$entry"
        printf '    %d) %-42s %-8s %s\n' "$i" "$repo" "$size" "$desc" >&2
        i=$((i + 1))
    done
    local ans
    read -r -p "Model [1-${#MODEL_CHOICES[@]}, default 1] " ans < "$TTY" || ans=""
    ans="${ans:-1}"
    if ! [[ "$ans" =~ ^[0-9]+$ ]] || (( ans < 1 || ans > ${#MODEL_CHOICES[@]} )); then
        warn "invalid choice '${ans}'; using the recommended default"
        ans=1
    fi
    printf '%s' "${MODEL_CHOICES[$((ans - 1))]%%|*}"
}

# ── step 4: interactive configuration ───────────────────────────────────
CONFIG_PATH="${XDG_CONFIG_HOME:-$HOME/.config}/stenographer/config.toml"
configure() {
    if [[ -f "$CONFIG_PATH" ]]; then
        if ! ask_yn "Config already exists at ${CONFIG_PATH}; reconfigure it?" "N"; then
            ok "keeping existing config"
            return
        fi
    fi

    # Materialize the full commented default config, then patch chosen keys.
    "$STENO" doctor >/dev/null 2>&1 || true
    [[ -f "$CONFIG_PATH" ]] || { warn "could not create default config; skipping."; return; }

    local hotkey
    hotkey=$(ask_default "Hotkey (evdev key name)" "KEY_RIGHTCTRL")

    info "Available audio input devices:"
    "$STENO" devices 2>/dev/null || warn "  (could not list devices)"
    local mic
    mic=$(ask_default "Mic device (name or index; empty = system default)" "")

    local model
    model=$(pick_model)

    # These lines exist verbatim in the generated default config.
    sed -i -E "s|^hotkey\.binding = .*|hotkey.binding = \"${hotkey}\"|" "$CONFIG_PATH"
    sed -i -E "s|^audio\.input_device = .*|audio.input_device = \"${mic}\"|" "$CONFIG_PATH"
    sed -i -E "s|^asr\.model = .*|asr.model = \"${model}\"|" "$CONFIG_PATH"
    ok "wrote config: ${CONFIG_PATH} (hotkey=${hotkey}, mic=${mic:-default}, model=${model})"
}

# ── step 5: ASR model ───────────────────────────────────────────────────
MODEL_READY=0
download_model() {
    local model size prompt
    model=$(config_model)
    size=$(model_size "$model")
    if [[ -n "$size" ]]; then
        prompt="Download the ASR model ${model} now (${size}, required to transcribe)?"
    else
        prompt="Download the ASR model ${model} now (required to transcribe)?"
    fi
    if ask_yn "$prompt" "Y"; then
        if "$STENO" model download; then
            MODEL_READY=1
            ok "model downloaded"
        else
            warn "model download failed; run \`stenographer model download\` later."
        fi
    else
        warn "skipped model download; run \`stenographer model download\` before use."
    fi
}

# ── step 6: systemd unit ────────────────────────────────────────────────
setup_service() {
    if ! command -v systemctl >/dev/null 2>&1; then
        warn "systemctl not available; skipping systemd setup. Run \`stenographer run\` manually."
        return
    fi
    if [[ "$MODEL_READY" -eq 1 ]]; then
        info "Installing, enabling, and starting the systemd user service ..."
        "$STENO" enable
        ok "systemd user service started"
    else
        # No model yet: install + enable the unit but don't start a daemon
        # that would fail its capability check and get restarted in a loop.
        info "Installing the systemd user service without starting it ..."
        "$STENO" enable --no-start
        warn "unit enabled but not started (no model yet)."
        warn "after \`stenographer model download\`, run \`stenographer start\`."
    fi
}

# ── run ─────────────────────────────────────────────────────────────────
if [[ "$DO_DEPS" -eq 1 ]]; then
    info "[1/6] Checking system dependencies ..."
    install_deps
else
    info "[1/6] Skipping system dependencies (--no-deps)."
fi
info "[2/6] Checking input-device permissions ..."
setup_input_group
info "[3/6] Installing the stenographer binary ..."
install_binary
info "[4/6] Configuring stenographer ..."
configure
info "[5/6] Preparing the speech-recognition model ..."
download_model
info "[6/6] Setting up the background service ..."
setup_service

echo
info "Verifying the installation ..."
"$STENO" doctor || true

echo
info "Done."
[[ "$RELOGIN_NEEDED" -eq 1 ]] && warn "Log out and back in to activate 'input' group membership."
printf '  Watch the daemon:  %sjournalctl --user -u stenographer.service -f%s\n' "$c_bold" "$c_reset"
printf '  Reconfigure:       edit %s then %sstenographer start%s (or restart the service)\n' \
    "$CONFIG_PATH" "$c_bold" "$c_reset"
