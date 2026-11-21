#!/bin/bash
# Baut das macOS-Paket (Apple Silicon): release/RORM Online.app (+ Zip)
#   Launcher + Server (gleiche App, "--server"), melonDS.app in Contents/Resources, mod/net.elf
# Voraussetzung: macOS, Python 3.11+, Internet (Pakete + melonDS-Download). Optional GITHUB_TOKEN für die API.
set -euo pipefail
VERSION="${1:-dev}"
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(dirname "$HERE")"
cd "$HERE"

python3 -m venv .venv-mac
PY="$HERE/.venv-mac/bin/python"
"$PY" -m pip install -q --upgrade pip
"$PY" -m pip install -q pywebview pysdl2 pysdl2-dll pyinstaller

# melonDS (offizielle macOS-Version) holen
MEL="$HERE/melonDS-mac"
if [ ! -d "$MEL/melonDS.app" ]; then
  rm -rf "$MEL"; mkdir -p "$MEL/dl"
  AUTH=(); [ -n "${GITHUB_TOKEN:-}" ] && AUTH=(-H "Authorization: Bearer $GITHUB_TOKEN")
  URL=$(curl -fsSL "${AUTH[@]}" https://api.github.com/repos/melonDS-emu/melonDS/releases/tags/1.1 |
        "$PY" -c "import json,sys; a=[x for x in json.load(sys.stdin)['assets'] if 'mac' in x['name'].lower()]; print(a[0]['browser_download_url'] if a else '')")
  [ -n "$URL" ] || { echo "Kein macOS-Download in melonDS 1.1 gefunden"; exit 1; }
  echo "Lade $URL"
  F="$MEL/dl/$(basename "$URL")"; curl -fsSL -o "$F" "$URL"
  case "$F" in
    *.zip) ditto -x -k "$F" "$MEL/dl/x" ;;
    *.dmg) MNT=$(hdiutil attach -nobrowse -readonly "$F" | tail -1 | awk -F'\t' '{print $NF}'); mkdir -p "$MEL/dl/x"; cp -R "$MNT"/*.app "$MEL/dl/x/"; hdiutil detach "$MNT" ;;
    *) echo "Unbekanntes Format: $F"; exit 1 ;;
  esac
  # manche Archive enthalten noch eine Zip mit der App
  for z in $(find "$MEL/dl/x" -name "*.zip"); do ditto -x -k "$z" "$MEL/dl/x"; done
  APP=$(find "$MEL/dl/x" -maxdepth 4 -name "melonDS.app" -type d | head -1)
  [ -n "$APP" ] || { echo "melonDS.app nicht gefunden"; find "$MEL/dl/x" -maxdepth 3; exit 1; }
  ditto "$APP" "$MEL/melonDS.app"; rm -rf "$MEL/dl"
fi

rm -rf build-mac dist-mac
"$PY" -m PyInstaller --noconfirm --clean --windowed --name "RORM Online" \
  --osx-bundle-identifier io.github.blwleon.rormonline \
  --add-data "ui:ui" --add-data "assets/melonDS.default.toml:assets" \
  --add-data "core/patch_rom.py:core" --add-data "core/blzlib.py:core" \
  --add-data "$REPO/patch/net.elf:mod" --add-data "$REPO/server/server.py:server" \
  --collect-all sdl2dll --distpath dist-mac --workpath build-mac main.py

APPDIR="dist-mac/RORM Online.app"
ditto "$MEL/melonDS.app" "$APPDIR/Contents/Resources/melonDS.app"
cp "$REPO/LICENSE" "$APPDIR/Contents/Resources/LICENSE.txt"
echo "$VERSION" > "$APPDIR/Contents/Resources/VERSION.txt"
# Ad-hoc-Signatur (ohne Apple-Konto) – nötig, damit die App auf Apple Silicon überhaupt startet
codesign --force --deep --sign - "$APPDIR"
codesign --verify --deep --strict "$APPDIR" && echo "Signatur ok"

rm -rf release-mac; mkdir -p release-mac
ditto "$APPDIR" "release-mac/RORM Online.app"
cp "$HERE/release_readme_mac.txt" "release-mac/LIES MICH - README.txt"
ditto -c -k --sequesterRsrc release-mac "release-mac-RORM-Online-$VERSION-macos.zip"
mv "release-mac-RORM-Online-$VERSION-macos.zip" "release-mac/RORM-Online-$VERSION-macos.zip"
echo "Fertig: $HERE/release-mac/RORM-Online-$VERSION-macos.zip"
