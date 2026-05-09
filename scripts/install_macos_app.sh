#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_SOURCE="$ROOT_DIR/dist/NixAI.app"
APP_TARGET="/Applications/NixAI.app"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "macOS app installation requires Darwin." >&2
  exit 1
fi

if [[ ! -d "$APP_SOURCE" ]]; then
  "$ROOT_DIR/scripts/build_macos_app.sh"
fi

rm -rf "$APP_TARGET"
cp -R "$APP_SOURCE" "$APP_TARGET"
echo "Installed $APP_TARGET"
