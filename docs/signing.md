# Building a signed Windows Portal.app

`scripts/build-app.sh` makes a real, shareable app: Python and Tk bundled with PyInstaller, signed with your
Developer ID, notarized, and carrying its own signed Wine loader for the native Apple Silicon engine. Without the
steps below it still builds, as an ad-hoc signed app for your own Mac. Its native engine then falls back to
Highball's loader.

## What you need

- **An Apple Silicon Mac** with **Xcode 26.4 or later**. The loader's link flag (`-x86_64_layout_emulation`) is new
  in that linker.
- **A python3 with Tk.** python.org's installer includes it; with Homebrew, run `brew install python-tk`.
- **A paid Apple Developer Program membership** (US$99 a year). You need it for a Developer ID certificate,
  notarization and the cross-architecture capability.

## One-time setup

1. **Certificate.** In Xcode → Settings → Accounts, add your Apple ID. Then Manage Certificates → + →
   **Developer ID Application**. It lands in your login keychain as
   `Developer ID Application: Your Name (TEAMID)`.
2. **App IDs.** At developer.apple.com → Certificates, Identifiers & Profiles → Identifiers, register two explicit
   App IDs:
   - the app, for example `com.yourname.windowsportal`;
   - the loader helper, for example `com.yourname.windowsportal.WineLoader`. Under its capabilities, enable
     **Cross-Architecture Support**. Highball's maintainer enabled it through the portal in October 2026. If the
     capability isn't listed for your account, Apple may grant it on request: ask through Developer Support.
3. **Provisioning profile.** Under Profiles → + → **Developer ID**, choose the helper's App ID and your certificate,
   then download the `.provisionprofile`. Keep it out of the repository: `signing/` is gitignored.
4. **Notarization credentials.** Make an app-specific password at account.apple.com, then run:
   ```sh
   xcrun notarytool store-credentials windows-portal --apple-id you@example.com --team-id TEAMID --password APP-SPECIFIC-PASSWORD
   ```

## Build

```sh
export WP_VERSION=1.0
export WP_BUNDLE_ID=com.yourname.windowsportal
export WP_LOADER_BUNDLE_ID=com.yourname.windowsportal.WineLoader
export WP_SIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
export WP_TEAM_ID=TEAMID
export WP_LOADER_PROFILE=signing/WineLoader.provisionprofile
export WP_NOTARY_PROFILE=windows-portal
export WP_DMG=1
scripts/build-app.sh
```

The script does five things, in this order:
1. Builds the app with a pinned PyInstaller.
2. Builds the loader (`helper/wineloader/build.sh`) and wraps it as `Contents/Helpers/WineLoader.app`, with your
   provisioning profile embedded.
3. Signs inside out. The app's Python libraries go first, then the helper with its entitlements, then the app's own
   seal.
4. Notarizes and staples the app.
5. Optionally builds, signs and notarizes `dist/Windows Portal.dmg`.

## Checking the result

```sh
codesign -d --entitlements - --xml "dist/Windows Portal.app/Contents/Helpers/WineLoader.app"   # lists cross-architecture-support
spctl -a -vv "dist/Windows Portal.app"                                                         # "accepted, source=Notarized Developer ID"
```

Then, on a Mac with macOS 26.5 or later:
1. Open the app and choose Manage Bottles → Get Native Engine….
2. Make a new bottle on the native engine and install something small. Notepad++ or 7-Zip will do.

The engine's `engine/lib/wine/aarch64-unix/wine` should be a symlink into `Windows Portal.app`. If it points into
Highball.app instead, the app's own helper isn't entitled. Check the profile, the team id and the bundle id.

## Licensing

- `helper/wineloader/main.c` is Wine's loader with Highball's two changes, LGPL-2.1-or-later (`COPYING.LIB`). The
  helper is a separate program inside the app, so its source must stay available, which this repository does.
- PyInstaller's bootloader is GPL with an exception that allows bundling any program.
- Python and Tk are under their own permissive licenses.
- Engines, graphics layers and store tools are downloaded on demand, never bundled.
