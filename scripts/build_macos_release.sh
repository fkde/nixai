#!/usr/bin/env bash
set -euo pipefail

# Build NixAI.app and package it as a zip suitable for a GitHub Release.
# The resulting archive is consumed by the in-app updater (app/api/updates.py).

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Release archives for macOS must be built on macOS." >&2
  exit 1
fi

"$ROOT_DIR/scripts/build_macos_app.sh"

APP_PATH="$ROOT_DIR/dist/NixAI.app"
if [[ ! -d "$APP_PATH" ]]; then
  echo "Expected $APP_PATH to exist after build." >&2
  exit 1
fi

VERSION="$(python3 -c 'from app.__version__ import __version__; print(__version__)')"
RELEASE_DIR="$ROOT_DIR/dist/release"
ZIP_NAME="NixAI-${VERSION}-macos.zip"
ZIP_PATH="$RELEASE_DIR/$ZIP_NAME"

mkdir -p "$RELEASE_DIR"
rm -f "$ZIP_PATH" "$ZIP_PATH.sha256"

# ditto preserves bundle resource forks, symlinks, and code signatures.
/usr/bin/ditto -c -k --sequesterRsrc --keepParent "$APP_PATH" "$ZIP_PATH"

(cd "$RELEASE_DIR" && shasum -a 256 "$ZIP_NAME" > "$ZIP_NAME.sha256")

echo "Release archive: $ZIP_PATH"
echo "Checksum:        $ZIP_PATH.sha256"
echo
echo "Publish to GitHub Releases (tag v${VERSION}):"
echo "  gh release create v${VERSION} \"$ZIP_PATH\" \"$ZIP_PATH.sha256\" --title \"v${VERSION}\" --notes \"...\""
