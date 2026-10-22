Free alternative to CrossOver: run Windows apps and games on MacOS

## Will my game run?

`python3 portal.py compat "Elden Ring"` (or a Steam app id) looks the game up in
[highball-db](https://github.com/gauthierpiarrette/highball-db), the open compatibility database behind
[Highball](https://github.com/gauthierpiarrette/highball): verified/community verdicts, the best renderer, known
issues and fixes, and a kernel-anti-cheat blocklist. The library shows the same verdict for synced Steam games, warns
before launching one that can't run, and sends games the database says run best on D3DMetal to the GPTK bottle.

Curated entries are CC0; entries marked "prediction" are derived from ProtonDB (ODbL) and only odds, not a Mac
verification. Lookups are cached for a week in `~/Library/Caches/WindowsPortal/compat`.

[Bridgeplay](https://bridgeplay.dev)'s tested list is the second source: games its maintainer ran on WineCX with
Apple's D3DMetal, which often covers new DirectX 12 games before Highball rates them. When Highball has no curated
entry, its result is the verdict shown ("Runs perfectly on D3DMetal (Bridgeplay's test)"), and `compat` prints both.

When a game you launched from the library closes, Windows Portal asks once how it ran (Smooth, Has issues, Didn't
run) and remembers the answer with the engine and graphics layer, on this Mac only (`python3 portal.py reports`).
Report… on the game's page drafts a GitHub issue from it, so what you found can reach others.

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
- **Amazon Games** (Prime Gaming): through [Nile](https://github.com/imLinguin/nile), Heroic's Amazon client,
  downloaded on first use. Sign in on Amazon's page and paste the address you land on.

Covers come from Steam for Steam games and for any game the [umu database](https://github.com/Open-Wine-Components/umu-database)
matches to one on Steam (which also brings that game's compatibility verdict). For the rest, add a free
[SteamGridDB](https://www.steamgriddb.com) key: `python3 portal.py art-key KEY`, or Cover Art… in a store view.

Logins are kept in `~/Library/Application Support/WindowsPortal/stores` (readable only by you) and
Epic's in `…/WindowsPortal/legendary`. Disconnect removes them.

## Per-game settings and fixes

- **Display**: `python3 portal.py display NAME retina` renders at the screen's full resolution (sharp, slower);
  `compact` does too with smaller text; `standard` is Wine's default. Manage Bottles → Display….
- **Game settings** (Game Settings… on a program, or `python3 portal.py game NAME PROGRAM SETTING VALUE`):
  `graphics` picks a layer for one game; `mouse force` fixes games whose camera spins or that lose the pointer.
  They key on the program's .exe, so they also apply when Steam or a launcher starts it (on wine10, a game's
  graphics layer reaches Steam games only if Steam wasn't already running).
- **Repair Steam** (`python3 portal.py steam-repair NAME`): stops everything in the bottle, clears Steam's web
  cache, removes a steam.cfg that blocks its self-update, starts Steam and checks its window comes up.
- **Force Quit** now also stops processes that outlive Wine's own shutdown, so nothing keeps running after a game.
- **Built-in fixes** for Steam games that need one, keyed on app id and applied when the game starts from the
  library: Deadlock's crackling audio and black Vulkan screen, Mortal Kombat 1's dead controllers, Resident Evil
  Requiem hiding DLSS under Wine, CONTROL Resonant's broken models on Metal 4, It Takes Two's shader stutter. Games
  that can't run (ray tracing only, VR only) get a warning before launch. The game's page shows what applies;
  `python3 portal.py compat GAME` prints it with its source. Your own go in
  `~/Library/Application Support/WindowsPortal/gamefixes.json`, keyed the same way, and win per game:
  `{"1422450": {"args": ["-dx11"], "env": {"SteamDeck": "1"}, "graphics": "d3dmetal", "note": "why"}}`.
- **More per game** (Game Settings…, or `python3 portal.py game NAME PROGRAM SETTING VALUE`): `args "-dx11"` adds
  launch arguments (Steam passes them on too); `hud on` shows Metal's performance HUD; `upscale on` turns on MetalFX
  spatial upscaling for DXMT (render lower, show sharp); `dlss on` makes D3DMetal report an NVIDIA RTX 4090 and
  turns on Apple's nvapi64 and nvngx, so games offer DLSS and MetalFX answers it (Game Porting Toolkit 4's D3DMetal;
  some games then take NVIDIA-only paths, so it's off by default); `env KEY=VALUE` sets a graphics layer's switch
  (`D3DM_*`, `DXMT_*`, `DXVK_*`, `MVK_*`, `VKD3D_*`), `SteamDeck`, `WINEDEBUG` or Wine's memory knobs for one game.
  Launch arguments always reach a Steam game; its environment and graphics layer do when launching it starts Steam.

Display profiles, per-game mouse settings and Steam repair are adapted from
[Mac Wine Launcher](https://github.com/MrBurge2000/mac-wine-launcher) (MIT). The per-game fixes, the DLSS and
MetalFX switches and the post-game report follow [Bridgeplay](https://github.com/raymondchins/Bridgeplay) (GPL-3.0),
as ideas and facts, not code. Everything this runs on, with licenses, is in [docs/third-party.md](docs/third-party.md).

## Native Apple Silicon engine (preview, optional)

`python3 portal.py get-engine arm64` (or Manage Bottles → Get Native Engine…) installs
[Highball](https://github.com/gauthierpiarrette/highball)'s native Wine for Apple Silicon. Windows programs run through
FEX instead of Rosetta, which Apple is winding down after macOS 27. It needs an Apple Silicon Mac with macOS 26.5 or later
and **Highball installed**: its Wine loader needs an Apple entitlement only a signed app can carry, so Windows Portal
borrows the signed loader inside Highball.app (or the one `WINDOWSPORTAL_WINELOADER` names).

- Graphics are `vkd3d` (DirectX 10–12, the default), `dxvk` (DirectX 10–11) and `wined3d`. No D3DMetal or DXMT, so
  many games run slower than on `wine10` today.
- Make a new bottle for it (`python3 portal.py new NAME win10 arm64`); bottles don't convert between it and the Intel
  engines. `python3 portal.py copy-games OLD NEW` clones `C:\Games` across without using extra disk.

A release build of Windows Portal.app carries its own signed loader instead: `scripts/build-app.sh` bundles Python,
builds the loader from `helper/wineloader` (Wine's, LGPL), signs and notarizes. Setup is in
[docs/signing.md](docs/signing.md), the reasoning in [docs/arm64-engine-plan.md](docs/arm64-engine-plan.md).
