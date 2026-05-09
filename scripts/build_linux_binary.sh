#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON:-python3}"
INSTALL_DEPS=0

for arg in "$@"; do
  case "$arg" in
    --install-deps)
      INSTALL_DEPS=1
      ;;
    -h|--help)
      cat <<'HELP'
Build the NixAI Linux binary for the current machine.

Usage:
  ./scripts/build_linux_binary.sh [--install-deps]

Environment:
  PYTHON=python3.11  Override Python executable.

Output:
  dist/nixai
HELP
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "Linux binary builds must run on Linux. PyInstaller does not cross-compile reliably." >&2
  exit 1
fi

cd "$ROOT_DIR"

if [[ "$INSTALL_DEPS" -eq 1 ]]; then
  "$PYTHON_BIN" -m pip install -r requirements.txt -r requirements-desktop.txt
fi

"$PYTHON_BIN" -m PyInstaller --clean -y nixai.spec

echo "Built $ROOT_DIR/dist/nixai"
