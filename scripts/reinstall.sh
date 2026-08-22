#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Force a fresh bundle build, then install it for the current user.
set -euo pipefail

cd "$(dirname "$0")/.."

build_args=()
for arg in "$@"; do
    case "${arg}" in
        --verbose) build_args=(--verbose) ;;
        --help|-h)
            exec scripts/install.sh "${arg}"
            ;;
    esac
done

scripts/build.sh "${build_args[@]}"
echo
scripts/install.sh "$@"
