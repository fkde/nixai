#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ICONSET_DIR="$ROOT_DIR/assets/macos/NixAI.iconset"
ICON_SVG="$ICONSET_DIR/icon_16x16.svg"
ICON_ICNS="$ROOT_DIR/assets/macos/NixAI.icns"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "macOS app builds require Darwin because iconutil and sips are macOS tools." >&2
  exit 1
fi

if [[ ! -f "$ICON_SVG" ]]; then
  echo "Missing icon source: $ICON_SVG" >&2
  exit 1
fi

mkdir -p "$ICONSET_DIR"
for size in 16 32 128 256 512; do
  sips -s format png -z "$size" "$size" "$ICON_SVG" --out "$ICONSET_DIR/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -s format png -z "$double" "$double" "$ICON_SVG" --out "$ICONSET_DIR/icon_${size}x${size}@2x.png" >/dev/null
done

iconutil -c icns "$ICONSET_DIR" -o "$ICON_ICNS"
python3 -m PyInstaller --clean nixai-mac.spec

echo "Built $ROOT_DIR/dist/NixAI.app"
