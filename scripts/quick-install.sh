#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Install, update, or repair from the latest published GitHub release. Meant to
# be run as
#
#   curl -fsSL https://harrison-blair.github.io/stenographer/install.sh | bash
#
# Downloads the native standalone bundle, the matching source distribution and
# SHA256SUMS, verifies the checksums, drops the bundle into the source tree's
# dist/ and runs that tree's scripts/install.sh on it — so no Python, venv or
# build toolchain is needed. A running service restarts on the new version; a
# stopped service, or a new install, stays stopped; a disabled service stays
# disabled. Any options are forwarded to install.sh
# (curl ... | bash -s -- --no-start).
set -euo pipefail

REPO="Harrison-Blair/stenographer"

usage() {
    cat <<EOF
Usage: quick-install.sh [install.sh options]

Install, update, or repair stenographer for the current user, using the latest
published release:

  curl -fsSL https://harrison-blair.github.io/stenographer/install.sh | bash

Steps:
  1. Resolve the latest release and download the native standalone bundle,
     the source distribution and SHA256SUMS
  2. Verify the checksums
  3. Run the source distribution's scripts/install.sh on the prebuilt bundle

A running service restarts on the new version. A stopped service stays stopped.
A disabled service stays disabled. A new install is enabled, stays stopped, and
prints the setup step.

Every option is forwarded to install.sh (--no-enable, --no-start,
--install-dir DIR, --verbose). When piping from curl, pass them after
"bash -s --".
EOF
    exit 64
}

die() {
    echo "error: $*" >&2
    exit 1
}

main() {
    local user_no_start=0 user_no_enable=0
    for arg in "$@"; do
        case "${arg}" in
            --help|-h) usage ;;
            --no-start) user_no_start=1 ;;
            --no-enable) user_no_enable=1 ;;
        esac
    done

    [[ "$(uname -s)" == "Linux" ]] || die "stenographer's prebuilt bundle is Linux-only"
    local arch
    case "$(uname -m)" in
        x86_64) arch="x86_64" ;;
        aarch64|arm64) arch="aarch64" ;;
        *) die "no prebuilt bundle for $(uname -m); build from source instead (see docs/building.md)" ;;
    esac
    for tool in curl tar sha256sum; do
        command -v "${tool}" >/dev/null || die "required tool not found: ${tool}"
    done

    echo "==> resolving the latest release ..."
    local tag version
    tag=$(curl -fsSLI -o /dev/null -w '%{url_effective}' \
        "https://github.com/${REPO}/releases/latest")
    tag="${tag##*/}"
    [[ "${tag}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] \
        || die "could not resolve a published release (got '${tag}')"
    version="${tag#v}"

    local base bundle sdist
    base="https://github.com/${REPO}/releases/download/${tag}"
    bundle="stenographer-${version}-linux-${arch}.tar.gz"
    sdist="stenographer-${version}.tar.gz"
    # Deliberately not local: the EXIT trap runs after main has returned.
    tmp=$(mktemp -d)
    keep_tmp=0
    trap '[[ "${keep_tmp}" -eq 1 ]] || rm -rf -- "${tmp}"' EXIT

    echo "==> downloading ${tag} (${arch}) ..."
    for file in SHA256SUMS "${sdist}" "${bundle}"; do
        curl -fL --progress-bar --retry 3 -o "${tmp}/${file}" "${base}/${file}"
    done

    echo "==> verifying checksums ..."
    grep -E " (${bundle}|${sdist})$" "${tmp}/SHA256SUMS" > "${tmp}/expected.sums" || true
    [[ "$(wc -l < "${tmp}/expected.sums")" -eq 2 ]] \
        || die "SHA256SUMS for ${tag} does not list both ${bundle} and ${sdist}"
    (cd "${tmp}" && sha256sum --check --strict --quiet expected.sums) \
        || die "checksum verification failed"

    echo "==> unpacking ..."
    local src="${tmp}/stenographer-${version}"
    tar -xzf "${tmp}/${sdist}" -C "${tmp}"
    mkdir -p "${src}/dist"
    tar -xzf "${tmp}/${bundle}" -C "${src}/dist"
    [[ -x "${src}/dist/stenographer/stenographer" ]] \
        || die "unexpected bundle layout in ${bundle}"
    [[ -x "${src}/scripts/install.sh" ]] \
        || die "unexpected source layout in ${sdist}"
    echo

    local new_install=0
    [[ -e "${HOME}/.local/bin/stenographer" ]] || new_install=1
    local install_args=("$@")
    local service_active=0 start_after=0
    if systemctl --user is-active --quiet stenographer.service 2>/dev/null; then
        service_active=1
    elif [[ "${user_no_start}" -eq 0 ]]; then
        install_args+=(--no-start)
    fi
    # Only the printed word counts: a missing unit or systemctl prints something
    # else, so a new install still gets enabled.
    if [[ "$(systemctl --user is-enabled stenographer.service 2>/dev/null)" == "disabled" ]] &&
       [[ "${user_no_enable}" -eq 0 ]]; then
        install_args+=(--no-enable)
        # install.sh's --no-enable also skips the start, so a running service
        # that is disabled restarts here.
        if [[ "${service_active}" -eq 1 && "${user_no_start}" -eq 0 ]]; then
            start_after=1
        fi
    fi

    if ! "${src}/scripts/install.sh" "${install_args[@]}"; then
        keep_tmp=1
        echo "error: install.sh failed; downloaded files kept in ${tmp}" >&2
        echo "       log: ${src}/dist/install.log" >&2
        exit 1
    fi

    if [[ "${start_after}" -eq 1 ]]; then
        systemctl --user start stenographer.service \
            || die "the service failed to start; see: journalctl --user -u stenographer"
    fi

    if [[ "${new_install}" -eq 1 ]]; then
        echo
        echo "Next, configure stenographer and build the speech model, then start it:"
        echo "  ~/.local/bin/stenographer setup --quick"
        echo "  systemctl --user start stenographer.service"
    fi
}

main "$@"
