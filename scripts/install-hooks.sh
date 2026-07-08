#!/usr/bin/env bash
# Point git at the repo's tracked hooks (.githooks/).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
git config core.hooksPath .githooks
echo "Installed: git hooks now run from .githooks/"
