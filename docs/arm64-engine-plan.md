# Plan: a native Apple Silicon engine

Status: draft, October 2026. Nothing here is built yet.

## Why

Every engine Windows Portal runs today (`wine10`, `wine`, `gptk`) is an Intel build. On Apple Silicon each Wine
process runs through Rosetta 2. Apple has said Rosetta stays fully available through macOS 27, and after that only
a reduced part of it remains, aimed at older games. Whether that part still covers Wine is not known. Highball
expects macOS 28 to retire most of Rosetta and has started a native line for that reason.

A native engine is also the only route to a few games the Intel engines cannot start. Highball's first native build
was made for Microsoft Flight Simulator 2024.

## What a native engine is

- **Wine itself is arm64.** WineHQ's development release is built for Apple Silicon as ARM64X images, so the
  Windows half of Wine also runs natively.
- **x86 Windows programs run through FEX instead of Rosetta.** FEX is an open-source x86 emulator. Wine loads it
  under the names of its emulator plug-ins (`xtajit64.dll` for 64-bit programs, `xtajit.dll` for 32-bit ones),
  the same interface Windows on ARM uses. Games stay x86; only the emulator changes.
- **Graphics are DXVK and vkd3d-proton on MoltenVK.** Both are built as ARM64EC. There is no D3DMetal (Apple ships
  it for Intel Wine only) and no DXMT on this line. Direct3D 9 is Wine's own.

Highball's preview, `arm64-wine11.18-r1` (15 October 2026):

| Part | What it is | Size | SHA-256 |
|---|---|---|---|
| engine + frameworks | Wine 11.18 with Highball's arm64 patches 0001–0038, FEX 2610 with 18 patches, Wine Mono, Gecko, a GStreamer framework that uses VideoToolbox for video | 403 MB (one archive) | `01dd2f61…63fdb19fb0` |
| moltenvk | MoltenVK 1.4.2 with 12 patches, including an on-disk pipeline cache so a game's second start compiles no shaders | 1.6 MB | `feaab38a…cb477d18496` |
| renderers | vkd3d-proton 3.1 and DXVK 3.1, ARM64EC | 11.8 MB | `9476a69f…c577e15136` |

Measured by Highball on a base M4 with macOS 27.0: Flight Simulator 2024 runs at 15–20 fps on the Medium preset at
1080p, stable over 25 minutes. That was through their test harness, not yet through their app's installer. It
requires macOS 15 or later.

## The blocker: a restricted Apple entitlement

A Wine that runs x86 code natively needs Apple's **cross-architecture entitlement**
(`com.apple.developer.cross-architecture-support`) on its loader process. Without it, the kernel won't let the
process do three things FEX needs:
- reserve the x18 register for the Windows thread block;
- map memory in the low 4 GB;
- switch memory ordering per thread.

The entitlement has these consequences:

- **A signed app bundle must carry it,** together with a provisioning profile from a paid Apple Developer account
  (US$99 a year). It cannot sit on a file inside a downloaded engine, and Windows Portal (a Python script, or a
  bundle with a symlinked Python) cannot carry it as things stand.
- **Highball ships it as a separate helper bundle,** `WineLoader.app` inside `Highball.app/Contents/Helpers/`. Each
  native engine's `engine/bin/wine` and `engine/lib/wine/aarch64-unix/wine` become symlinks to that helper. The
  helper finds `ntdll.so` beside the path it was started from, so one signed bundle serves every engine.
- **Building the loader takes Xcode 26.4's linker** (`-x86_64_layout_emulation`) plus a raised `__PAGEZERO` and
  image base (`0x170000000`). It also has to link against SDK version 11.0, because binaries built against a newer
  SDK lose x18 on context switches.

## Options

### A. Use Highball's signed helper when it is installed (recommended first)

If `/Applications/Highball.app` exists, Windows Portal uses its `Contents/Helpers/WineLoader.app/Contents/MacOS/wine`
as the loader for the engine archive it downloads.

- **Pros:** no Apple account, no signing work, and it can ship as a preview within days. The helper is a separate
  program that Windows Portal only runs, so Highball's GPL license does not reach Windows Portal's code. The engine
  archives are already public and pinned by hash.
- **Cons:** it depends on Highball being installed and on the helper's location and behaviour staying the same.
  Highball's own install flow for this engine is unfinished, so problems may be theirs or ours.
- **Before relying on it:** ask Highball's maintainer, through their Discord or an issue, whether other launchers
  may use the helper this way, and whether they would document its location as stable.

### B. Ship Windows Portal's own signed helper (the long-term answer)

- Join the Apple Developer Program, enable the cross-architecture capability for a helper bundle ID (Highball got it
  through the developer portal), and make a Developer ID provisioning profile.
- Build the loader. Highball's `spike/wineloader/main.c` is GPL-3.0, so copying it makes the helper GPL. Keeping
  the helper a separate binary under its own license is fine, but say so in the README. Writing it from scratch is
  possible; it is small, but the memory layout is subtle.
- Sign it with hardened runtime and these entitlements: cross-architecture-support, allow-jit,
  allow-unsigned-executable-memory, disable-library-validation and allow-dyld-environment-variables. Then notarize.
- This only makes sense once Windows Portal itself ships as a real signed app rather than a script. `package()`
  currently symlinks the machine's Python and cannot be distributed. That is a project of its own: PyInstaller or
  py2app, a Developer ID, notarization.

### C. Wait for someone else's signed loader

CodeWeavers will need the same thing for CrossOver, and Gcenx may produce arm64 builds. But a signed loader is tied
to its publisher's bundle, so another project's helper would be used the same way as option A. Waiting gains
nothing, except evidence about which loader becomes the common one.

**Recommendation:** ship option A as an opt-in preview now. Plan option B together with real app packaging, and
decide on it by spring 2027, ahead of macOS 28.

## Implementation in Windows Portal (option A)

1. **Detection and gating.** An `arm64` engine appears only on an Apple Silicon Mac with macOS 15 or later when the
   helper exists. Otherwise `get-engine arm64` explains what is missing.
2. **Pinned download.** Add `arm64-engine`, `arm64-moltenvk` and `arm64-renderers` to `PINNED` with the hashes above
   (full values in Highball's `spike/engines/arm64-wine11.18-r1.json`).
   - Unpack `engine/` and `frameworks/` from the one archive.
   - Put MoltenVK at `engine/lib/libMoltenVK.dylib`, replacing the archive's copy, and the renderers under
     `renderers/`.
   - Rename into place only when complete, as `get_engine` already does.
3. **Loader links.** Point `engine/bin/wine` and `engine/lib/wine/aarch64-unix/wine` at the helper, keeping the
   archive's unsigned loader aside as `wine.unsigned`. Check the links on every launch, so a moved or updated
   Highball heals them.
4. **Environment** (`engine_env`):
   - `GST_PLUGIN_PATH` into `frameworks/`;
   - `MVK_CONFIG_SHADER_SOURCE_COMPRESSION_ALGORITHM=1`, `MVK_CONFIG_RESUME_LOST_DEVICE=1` and
     `DXVK_RELAX_FEATURES=1`;
   - no `ROSETTA_ADVERTISE_AVX`;
   - renderer folders through `WINEDLLPATH`;
   - graphics choices `vkd3d` (DirectX 12, plus 10 and 11 through its DXGI), `dxvk` and `wined3d`. `GRAPHICS["arm64"]`
     gets a new `vkd3d` entry, and `RENDERERS` gets its name.
5. **Bottles never move between the Intel engines and this one.** Highball's rule too: the prefix layout differs.
   `set_engine` refuses both directions. A "Copy Games" action can clone `drive_c/Games` into a new native bottle
   with `cp -c`, which takes no extra disk space.
6. **Compatibility verdicts.** Highball's database names `d3dmetal` or `dxmt` for most games. On a native bottle,
   show "best on D3DMetal (not available on the native engine)" rather than offering a switch. Watch for
   arm64-specific fields as Highball adds them.
7. **Steam.** Steam's 32-bit bootstrapper would run through FEX under WoW64, which is untested here. Keep the
   webhelper stand-in, which is engine-independent. The stand-in is compiled for x86-64, so it runs through FEX
   like Steam's own.

## Testing

Each game is run on the same Mac with `wine10` and with the native engine:

| Game | Why |
|---|---|
| Microsoft Flight Simulator 2024 | Highball's verified case, so it shows whether our install path matches theirs |
| Steam client: login, store, downloads | 32-bit bootstrapper through FEX, Chromium web views |
| Portal (DirectX 9) | Wine's own Direct3D 9 on this line, against DXVK's on `wine10` |
| A DirectX 11 game with a DXMT verdict | The cost of losing DXMT |
| A DirectX 12 game with a D3DMetal verdict, such as Cyberpunk 2077 | vkd3d-proton against D3DMetal |
| A 32-bit game | WoW64 + FEX |

Record fps, first and second start times (the shader cache), memory, and anything broken. Repeat on one M1 and one
M3 or later.

## Open questions

- Does the post-macOS-27 Rosetta subset keep running Intel Wine? If so, the native engine is an option rather than
  a necessity, and option B can wait.
- Will Highball keep `WineLoader.app` at its current path, and accept other launchers using it?
- Can FEX's performance (Highball reports about 15–20 fps on a base M4 in Flight Simulator) come close to Rosetta's
  for the DirectX 11 catalog, where `wine10` + DXMT is strong today?
- When does DXMT gain an arm64 build? DXMT talks to Metal directly, so it should port. If it does, the DirectX 11
  gap closes.

## Sources

- Highball engine manifest `spike/engines/arm64-wine11.18-r1.json`, and `WineLoaderHelper.swift`,
  `spike/wineloader/build.sh` and `Scripts/make-app.sh` in github.com/gauthierpiarrette/highball.
- Apple, WWDC 2025 Platforms State of the Union: the Rosetta timeline.
