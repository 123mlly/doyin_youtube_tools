#!/usr/bin/env bash
# Build standalone GUI from repository root (macOS / Linux).
# Produces dist/DouyinDownloaderGui/ ; on macOS also dist/DouyinDownloaderGui.app
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python3 -m pip install -q -e ".[gui,build-gui]"
python3 -m PyInstaller --noconfirm --clean "${ROOT}/packaging/DouyinDownloaderGui.spec"
echo "Done. See ${ROOT}/dist/"
