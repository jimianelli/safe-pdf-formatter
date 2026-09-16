#!/bin/bash
# Maintainer build script. End users only need the resulting .app and config.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYINSTALLER_CONFIG_DIR="$PWD/build/pyinstaller-cache"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Build the macOS app on a Mac."
  exit 1
fi
if [[ ! -x .venv/bin/python ]]; then
  "${SAFE_FORMATTER_PYTHON:-python3}" -m venv .venv
fi
if [[ "${SAFE_FORMATTER_SKIP_INSTALL:-0}" != "1" ]]; then
  if ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
    .venv/bin/python -m ensurepip --upgrade
  fi
  .venv/bin/python -m pip install -r requirements-build.txt
fi
.venv/bin/python -m PyInstaller --noconfirm --clean \
  --workpath build/pyinstaller --distpath dist "SAFE PDF Formatter.spec"
.venv/bin/python scripts/package_release.py
.venv/bin/python scripts/verify_build.py
echo "Built release/SAFE PDF Formatter-macOS-$(uname -m)"
