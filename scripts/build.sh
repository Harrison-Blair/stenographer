#!/usr/bin/env bash
# Build a self-contained stenographer binary via PyInstaller.
# Output: dist/stenographer/stenographer
set -euo pipefail

cd "$(dirname "$0")/.."

.venv/bin/pyinstaller --noconfirm --clean packaging/stenographer.spec

echo
echo "Built: dist/stenographer/stenographer"
echo "Run:   ./dist/stenographer/stenographer --version"
echo "Run:   ./dist/stenographer/stenographer doctor"
