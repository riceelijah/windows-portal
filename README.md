Free alternative to CrossOver: run Windows apps and games on MacOS

## Will my game run?

`python3 portal.py compat "Elden Ring"` (or a Steam app id) looks the game up in
[highball-db](https://github.com/gauthierpiarrette/highball-db), the open compatibility database behind
[Highball](https://github.com/gauthierpiarrette/highball): verified/community verdicts, the best renderer, known
issues and fixes, and a kernel-anti-cheat blocklist. The library shows the same verdict for synced Steam games, warns
before launching one that can't run, and sends games the database says run best on D3DMetal to the GPTK bottle.

Curated entries are CC0; entries marked "prediction" are derived from ProtonDB (ODbL) and only odds, not a Mac
verification. Lookups are cached for a week in `~/Library/Caches/WindowsPortal/compat`.

## Keyboard

New bottles map Command to Ctrl (so ⌘C / ⌘V / ⌘A work in Windows apps) and Option to Alt.
`python3 portal.py keys NAME off` restores Wine's default, where Command acts as Alt.

## Graphics

Windows games draw with DirectX; a graphics layer translates it to Metal. Each bottle picks one
(`python3 portal.py graphics NAME LAYER`, or Manage Bottles → Graphics…):

| Layer | DirectX | Engines | Notes |
|---|---|---|---|
| `dxmt` | 10, 11 | wine10 | Straight to Metal; best for most DX11 games in Highball's database |
| `d3dmetal` | 9–12 | wine10, gptk | Apple's; the way to run DX12. Apple-licensed: `accept-d3dmetal` first on wine10 |
| `dxvk` | 9–11 | wine10, wine (experimental) | Through Vulkan/MoltenVK; often the most correct for older games |
| `wined3d` | 1–11 | wine10, wine | Wine's own, through OpenGL: slowest, works almost everywhere |

The `wine10` engine (`python3 portal.py get-engine wine10`, ~250 MB, also part of `setup`) is Sikarugir's
Wine 10, built from the CrossOver tree's Mac work, with its MoltenVK, GStreamer and the layers above,
pinned by SHA-256 to the same files Highball uses. It also has msync (`sync NAME msync`), which speeds
games up but hangs Steam's own window, so bottles with Steam default to `none`.

## Game stores

The sidebar's Stores section (or `python3 portal.py store …`) lists everything you own, installed or not:

- **Steam**: read from the Steam you're signed in to in a bottle. No password or API key. Install opens
  Steam's own download.
- **Epic Games**: through [Legendary](https://github.com/legendary-gl/legendary), downloaded on first use.
  Sign in on Epic's page and paste the code. Games install into `C:\Games` and launch with Epic's login
  token, without the Epic launcher.
- **GOG**: sign in on GOG's page and paste the address you land on. Installs download GOG's offline
  installer (every part of it) and run it.
- **itch.io**: paste a personal API key from itch.io's settings. Installs take the game's first Windows
  download, skipping demos.

Logins are kept in `~/Library/Application Support/WindowsPortal/stores` (readable only by you) and
Epic's in `…/WindowsPortal/legendary`. Disconnect removes them.
