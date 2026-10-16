#!/bin/zsh
# Builds a distributable "Windows Portal.app" on an Apple Silicon Mac: Python and Tk bundled by PyInstaller, plus the
# signed Wine loader helper the native engine needs (helper/wineloader). See docs/signing.md for the one-time setup.
#
# Settings (environment):
#   WP_VERSION           version string (default 1.0)
#   WP_BUNDLE_ID         the app's bundle id (default local.windowsportal; use your own reverse-DNS id for releases)
#   WP_LOADER_BUNDLE_ID  the helper's (default $WP_BUNDLE_ID.WineLoader); must match the App ID with the capability
#   WP_SIGN_IDENTITY     "Developer ID Application: Your Name (TEAMID)"; unset = ad-hoc signed development build
#   WP_TEAM_ID           your 10-character Apple team id (needed with WP_LOADER_PROFILE)
#   WP_LOADER_PROFILE    Developer ID provisioning profile for the helper's App ID (.provisionprofile)
#   WP_NOTARY_PROFILE    notarytool keychain profile (xcrun notarytool store-credentials NAME ...); set = notarize
#   WP_DMG=1             also make dist/Windows Portal.dmg
set -euo pipefail
cd "$(dirname "$0")/.."
[[ "$(uname -m)" == arm64 ]] || { echo "error: build on an Apple Silicon Mac (the helper is arm64)" >&2; exit 1; }
VERSION=${WP_VERSION:-1.0}
BUNDLE_ID=${WP_BUNDLE_ID:-local.windowsportal}
LOADER_ID=${WP_LOADER_BUNDLE_ID:-$BUNDLE_ID.WineLoader}
IDENTITY=${WP_SIGN_IDENTITY:-}
APP="dist/Windows Portal.app"
HELPER_BUILD=build/WineLoader.app
mkdir -p build dist

# 1. The app: PyInstaller, pinned, in its own virtualenv. Needs a python3 with Tk (python.org's, or Homebrew's
#    python-tk), since PyInstaller bundles the Tk the interpreter has.
python3 -c 'import tkinter' || { echo "error: this python3 has no Tk; install python.org's Python or brew install python-tk" >&2; exit 1; }
[[ -x build/venv/bin/pyinstaller ]] || { python3 -m venv build/venv && build/venv/bin/pip install -q pyinstaller==6.11.1; }
sips -s format icns -z 512 512 icon.png --out build/icon.icns >/dev/null
rm -rf "$APP"
build/venv/bin/pyinstaller --noconfirm --clean --windowed --name "Windows Portal" \
  --icon "$PWD/build/icon.icns" --osx-bundle-identifier "$BUNDLE_ID" --add-data "$PWD/icon.png:." \
  --distpath dist --workpath build/pyinstaller --specpath build portal.py >/dev/null
plutil -replace CFBundleShortVersionString -string "$VERSION" "$APP/Contents/Info.plist"
plutil -replace CFBundleVersion -string "$VERSION" "$APP/Contents/Info.plist"
plutil -replace LSApplicationCategoryType -string public.app-category.games "$APP/Contents/Info.plist"

# 2. The Wine loader helper (needs Xcode 26.4+). Without it the app still works; the native engine then falls back to
#    Highball's helper if Highball is installed.
rm -rf "$HELPER_BUILD"
if helper/wineloader/build.sh; then
  mkdir -p "$HELPER_BUILD/Contents/MacOS"
  cp build/wineloader/wine "$HELPER_BUILD/Contents/MacOS/wine"
  cat > "$HELPER_BUILD/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>$LOADER_ID</string>
  <key>CFBundleExecutable</key><string>wine</string>
  <key>CFBundleName</key><string>Windows Portal Wine Loader</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSBackgroundOnly</key><true/>
  <key>LSMinimumSystemVersion</key><string>26.5</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.games</string>
</dict></plist>
PLIST
  [[ -n "${WP_LOADER_PROFILE:-}" ]] && cp "$WP_LOADER_PROFILE" "$HELPER_BUILD/Contents/embedded.provisionprofile"
else
  echo "note: the Wine loader helper didn't build (Xcode 26.4 or later needed); the app ships without it" >&2
fi

# 3. Sign, inside out. The app's Python libraries first (--deep), before the helper is inside: --deep would re-sign
#    the helper without its entitlements. Then the helper, then the app's own seal over everything.
if [[ -n "$IDENTITY" ]]; then
  codesign --force --deep --options runtime --timestamp --entitlements scripts/app.entitlements -s "$IDENTITY" "$APP"
  if [[ -d "$HELPER_BUILD" ]]; then
    if [[ -f "$HELPER_BUILD/Contents/embedded.provisionprofile" ]]; then
      : "${WP_TEAM_ID:?set WP_TEAM_ID with WP_LOADER_PROFILE}"
      sed -e "s/TEAMID/$WP_TEAM_ID/g" -e "s/BUNDLEID/$LOADER_ID/g" helper/wineloader/wineloader.entitlements > build/wineloader.entitlements
      codesign --force --options runtime --timestamp --entitlements build/wineloader.entitlements -s "$IDENTITY" "$HELPER_BUILD"
    else  # a binary claiming the restricted entitlement without its profile is killed at exec, so sign it plain
      echo "note: no WP_LOADER_PROFILE: the helper is signed without the cross-architecture entitlement and won't run the native engine" >&2
      codesign --force --options runtime --timestamp -s "$IDENTITY" "$HELPER_BUILD"
    fi
    mkdir -p "$APP/Contents/Helpers" && cp -R "$HELPER_BUILD" "$APP/Contents/Helpers/"
  fi
  codesign --force --options runtime --timestamp --entitlements scripts/app.entitlements -s "$IDENTITY" "$APP"
  codesign --verify --strict --deep "$APP"
else
  [[ -d "$HELPER_BUILD" ]] && mkdir -p "$APP/Contents/Helpers" && cp -R "$HELPER_BUILD" "$APP/Contents/Helpers/"
  codesign --force --deep -s - "$APP"
  echo "note: ad-hoc signed development build (no WP_SIGN_IDENTITY); fine on this Mac, not for sharing" >&2
fi

# 4. Notarize and staple.
if [[ -n "$IDENTITY" && -n "${WP_NOTARY_PROFILE:-}" ]]; then
  ditto -c -k --keepParent "$APP" build/notarize.zip
  xcrun notarytool submit build/notarize.zip --keychain-profile "$WP_NOTARY_PROFILE" --wait
  xcrun stapler staple "$APP"
fi

# 5. Disk image.
if [[ "${WP_DMG:-}" == 1 ]]; then
  rm -f "dist/Windows Portal.dmg"
  hdiutil create -volname "Windows Portal" -srcfolder "$APP" -ov -format UDZO "dist/Windows Portal.dmg" >/dev/null
  [[ -n "$IDENTITY" ]] && codesign --force --timestamp -s "$IDENTITY" "dist/Windows Portal.dmg"
  [[ -n "$IDENTITY" && -n "${WP_NOTARY_PROFILE:-}" ]] && \
    xcrun notarytool submit "dist/Windows Portal.dmg" --keychain-profile "$WP_NOTARY_PROFILE" --wait && \
    xcrun stapler staple "dist/Windows Portal.dmg"
fi
echo "built $APP"
