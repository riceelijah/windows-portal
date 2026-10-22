# Third-party software and data

Windows Portal is a thin manager: the work is done by the projects below, which it downloads pinned by SHA-256 or
reads at run time. Each keeps its own license. Nothing here is modified or redistributed by this repository.

## Engines and graphics

| Component | Where it comes from | License | Used for |
|---|---|---|---|
| Wine (WineHQ) | [Gcenx/macOS_Wine_builds](https://github.com/Gcenx/macOS_Wine_builds) | LGPL-2.1+ | the `wine` engine |
| Sikarugir Wine 10 | [Sikarugir-App/Engines](https://github.com/Sikarugir-App/Engines) and Wrapper (CrossOver-tree Wine, MoltenVK, GStreamer, DXMT, DXVK, D3DMetal) | LGPL-2.1+ (Wine), see the bundle for the rest | the `wine10` engine |
| Highball native engine | [gauthierpiarrette/highball-engine](https://github.com/gauthierpiarrette/highball-engine) (Wine for arm64, FEX, MoltenVK, vkd3d, DXVK) | LGPL-2.1+ (Wine), MIT (FEX), Apache-2.0 (MoltenVK), LGPL-2.1+ (vkd3d) | the `arm64` engine |
| Wine loader (`helper/wineloader`) | Wine's `loader/`, built and signed by `scripts/build-app.sh` | LGPL-2.1+ (`helper/wineloader/COPYING.LIB`) | the native engine's entitled loader |
| Game Porting Toolkit (D3DMetal) | Apple, through Gcenx's Homebrew cask, or inside the Sikarugir bundle | Apple's, non-commercial, no modification or redistribution (`accept-d3dmetal` shows it) | the `gptk` engine and the `d3dmetal` layer |
| DXMT | [3Shain/dxmt](https://github.com/3Shain/dxmt), as bundled by Sikarugir | LGPL-2.1+ (MIT up to v0.80) | the `dxmt` layer |
| DXVK-macOS | [Gcenx/DXVK-macOS](https://github.com/Gcenx/DXVK-macOS) | zlib | the `dxvk` layer |
| winetricks | Homebrew | LGPL-2.1+ | `tricks` |

## Stores

| Component | Where it comes from | License | Used for |
|---|---|---|---|
| Legendary | [legendary-gl/legendary](https://github.com/legendary-gl/legendary), binary downloaded on first use | GPL-3.0 | Epic Games library and installs |
| Nile | [imLinguin/nile](https://github.com/imLinguin/nile), binary downloaded on first use | GPL-3.0 | Amazon Games library and installs |
| Steam, GOG, itch.io | their own public web APIs, with your sign-in | their terms | libraries and installs |

## Data read at run time

| Data | Source | License | Used for |
|---|---|---|---|
| Compatibility verdicts | [highball-db](https://github.com/gauthierpiarrette/highball-db) through gethighball.com | CC0 (curated); ODbL for ProtonDB-derived predictions | `compat`, the library's verdict line |
| Tested games | [Bridgeplay](https://github.com/raymondchins/Bridgeplay) `compat/games.json` | GPL-3.0 (the repository); shown with attribution, not copied into this one | a second verdict, `compat` |
| Steam matches for other stores' games | [umu-database](https://github.com/Open-Wine-Components/umu-database) | see the repository | cover art and verdicts for Epic, GOG, itch.io and Amazon games |
| Cover art | Steam's CDN; [SteamGridDB](https://www.steamgriddb.com) with your key | their terms | the library |
| Steam web helper stand-in | `steamwebhelper.c`, this repository | this repository's | keeps Steam's window alive under Wine |

## Ideas and fixes borrowed

- **[Bridgeplay](https://bridgeplay.dev)** (Raymond Chin, GPL-3.0): the per-game fixes in `GAMEFIXES` and their
  reasons (Deadlock's audio and renderer, Mortal Kombat 1's controllers, Resident Evil Requiem's DLSS switch, CONTROL
  Resonant's Metal 3 path, which games need ray tracing), the DLSS-through-MetalFX adapter trick, Metal HUD and
  MetalFX upscaling as per-game switches, and the one-tap "How did it run?" report when a game closes. Facts and
  ideas, written here anew; none of its code.
- **[Mac Wine Launcher](https://github.com/MrBurge2000/mac-wine-launcher)** (MIT): display profiles, per-game mouse
  settings, Steam repair.
- **[Highball](https://github.com/gauthierpiarrette/highball)**: the compatibility database, the native engine, the
  signed loader arrangement.
- **[PCGamingWiki](https://www.pcgamingwiki.com)** (CC BY-NC-SA 3.0): the renderer flags cited in `GAMEFIXES`.

Windows Portal is not affiliated with Apple, Valve, CodeWeavers or any of the projects above. "Wine" and "CrossOver"
are their owners' trademarks, used to describe what this runs with.
