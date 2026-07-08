#!/usr/bin/env bash
# Build the standalone binary, then install it. Thin wrapper that runs
# build.sh followed by install.sh. Extra args are passed to install.sh.
set -euo pipefail

cd "$(dirname "$0")"

./build.sh
./install.sh "$@"
