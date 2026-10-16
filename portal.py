#!/usr/bin/env python3
"""Windows Portal: a free CrossOver-style bottle manager on top of Wine.

  python3 portal.py                        # GUI
  python3 portal.py setup                  # install Wine (Game Porting Toolkit) + winetricks
  python3 portal.py package [DIR]          # build "Windows Portal.app" (default ~/Applications)
  python3 portal.py new NAME [WINVER] [ENGINE]  # WINVER: win10 (default), win11, win7, winxp64...
                                           # ENGINE: wine10 (default once installed), wine (Wine 11) or gptk
  python3 portal.py engine NAME [ENGINE]   # show or switch a bottle's engine
  python3 portal.py get-engine wine10      # Wine 10 with DXMT, D3DMetal and DXVK (~250 MB)
  python3 portal.py get-engine arm64       # preview: native Apple Silicon Wine, no Rosetta (~415 MB; needs Highball.app)
  python3 portal.py graphics NAME [LAYER]  # show or set a bottle's graphics layer: dxmt, d3dmetal, dxvk, vkd3d, wined3d
  python3 portal.py accept-d3dmetal        # read and accept Apple's license, needed for d3dmetal on wine10
  python3 portal.py sync NAME [MODE]       # wine10 bottles: msync (fastest, default), esync or none (Steam's window)
  python3 portal.py display NAME [MODE]    # standard, retina (sharp, full resolution) or compact (retina, smaller text)
  python3 portal.py game NAME PROGRAM [SETTING VALUE]  # per-game: graphics LAYER|default, mouse enable|force|disable|default
  python3 portal.py steam-repair NAME      # stop everything in the bottle, clear Steam's web cache, start Steam, check it
  python3 portal.py copy-games FROM TO     # clone C:\\Games into another bottle (e.g. a new native one)
  python3 portal.py art-key KEY            # SteamGridDB API key, for cover art of games not on Steam
  python3 portal.py winver NAME [WINVER]   # show or change the Windows version (restart its programs after)
  python3 portal.py keys NAME [on|off]     # Command as Ctrl, Option as Alt (Mac copy/paste); on for new bottles
  python3 portal.py compat GAME            # will it run? Steam app id or title, from Highball's open database
  python3 portal.py list
  python3 portal.py catalog                # software the installer knows about
  python3 portal.py install NAME ITEM      # catalog item, or a path to an .exe/.msi/zip/7z/rar
  python3 portal.py programs NAME          # Start Menu shortcuts + added programs in a bottle
  python3 portal.py add NAME FILE [TITLE]  # add a program (e.g. a portable game) to the library
  python3 portal.py steam-sync             # clone games installed by Steam (any bottle) into the GPTK bottle
  python3 portal.py remove NAME TITLE      # remove it from the library
  python3 portal.py run NAME FILE [args]   # .exe, .msi, .bat or .lnk
  python3 portal.py app NAME FILE [TITLE]  # make a Mac app in ~/Applications/Windows Portal
  python3 portal.py config NAME            # winecfg
  python3 portal.py tricks NAME [verbs]    # winetricks (e.g. vcrun2022 corefonts)
  python3 portal.py kill NAME              # force quit everything in a bottle
  python3 portal.py export NAME DEST       # writes DEST.tar.gz
  python3 portal.py store login STORE [CODE]     # epic, gog, itch or amazon; without CODE, opens the sign-in page
  python3 portal.py store logout STORE
  python3 portal.py store list STORE             # steam, epic, gog, itch or amazon: everything you own
  python3 portal.py store install STORE ID NAME  # install a game you own into bottle NAME
  python3 portal.py store play STORE ID
  python3 portal.py import ARCHIVE
  python3 portal.py delete NAME

Every bottle is 64-bit and runs 32-bit programs too (WoW64); this Wine can't make pure 32-bit bottles.
Add your own installers to ~/Library/Application Support/WindowsPortal/catalog.json:
  {"My App": {"url": "https://.../setup.exe", "file": "myapp-setup.exe", "tricks": ["vcrun2022"]}}
"""
import base64, hashlib, json, os, platform, re, struct, time, zlib, plistlib, shlex, shutil, subprocess, sys, tarfile
import urllib.error, urllib.parse, urllib.request
from pathlib import Path

DATA = Path.home() / "Library/Application Support/WindowsPortal"
HOME = DATA / "bottles"
CACHE = Path.home() / "Library/Caches/WindowsPortal"
APPS = Path.home() / "Applications/Windows Portal"
WINE_VERSION = "11.18"  # Gcenx/macOS_Wine_builds, the official WineHQ macOS packages
WINE_URL = f"https://github.com/Gcenx/macOS_Wine_builds/releases/download/{WINE_VERSION}/wine-devel-{WINE_VERSION}-osx64.tar.xz"
WINE_SHA256 = "aa0ea4c82e636ae7bca2076387cb0a5affa26509ad13f119ecd0d62bd7ba6f82"
# Sikarugir's Wine 10 (built from the CrossOver tree's Mac work) plus its runtime: MoltenVK, GStreamer and the graphics
# layers (DXMT, D3DMetal, DXVK). Plain WineHQ builds lack the Mac driver hooks DXMT and D3DMetal need, and msync.
SIK = DATA / "engines/sikarugir-10.0_6"
# Preview: Highball's native Apple Silicon Wine (WineHQ 11.18 for arm64; x86 programs run through FEX, not Rosetta).
# Its loader needs Apple's cross-architecture entitlement, which only a signed app can carry, so it runs through the
# signed WineLoader helper inside Highball.app (docs/arm64-engine-plan.md, option A).
ARM = DATA / "engines/arm64-wine11.18-r1"
WINELOADER_PATHS = [Path(os.environ["WINDOWSPORTAL_WINELOADER"])] if os.environ.get("WINDOWSPORTAL_WINELOADER") else [
    Path(a) / "Highball.app/Contents/Helpers/WineLoader.app/Contents/MacOS/wine" for a in ("/Applications", Path.home() / "Applications")]
ENGINES = {  # per bottle
    "wine10": SIK / "wswine.bundle/bin/wine",
    "arm64": ARM / "engine/bin/wine",
    "wine": DATA / f"engines/wine-{WINE_VERSION}/Wine Devel.app/Contents/Resources/wine/bin/wine",
    "gptk": Path("/Applications/Game Porting Toolkit.app/Contents/Resources/wine/bin/wine64"),
}
ENGINE_NAMES = {"wine10": "Wine 10 (DXMT, D3DMetal, DXVK)", "arm64": "Native Apple Silicon (preview)",
                "wine": f"Wine {WINE_VERSION}", "gptk": "Game Porting Toolkit (DirectX 12)"}
ENGINE_AGE = {"gptk": 0, "wine10": 1, "wine": 2}  # Wine upgrades a prefix it opens; an older Wine can't open it after
GRAPHICS = {  # layers each engine can use, default first
    "wine10": ["dxmt", "d3dmetal", "dxvk", "wined3d"],
    "wine": ["wined3d", "dxvk"],  # DXVK here is experimental: these DXVK builds were made for CrossOver-tree Wine
    "gptk": ["d3dmetal"],
    "arm64": ["vkd3d", "dxvk", "wined3d"],  # no D3DMetal or DXMT on arm64; vkd3d's folder also serves DirectX 10/11
}
PINNED = {  # download: (url, sha256). Pinned, so a changed file is refused rather than run.
    "wine": (WINE_URL, WINE_SHA256),
    "wine10": ("https://github.com/Sikarugir-App/Engines/releases/download/v1.0/WS12WineSikarugir10.0_6.tar.xz",
               "9da7ee0cbf386522f3a9906943726d9c3c125dbbd9ab120e3cde80e88d6091b2"),
    "wine10-runtime": ("https://github.com/Sikarugir-App/Wrapper/releases/download/v1.0/Template-1.0.11.tar.xz",
                       "9fa15479e7ff6abd99c1d07be285fb95f41fc6991586502427152b1f7d6ccb8a"),
    "dxvk": ("https://github.com/Gcenx/DXVK-macOS/releases/download/v1.10.3-20230507-repack/dxvk-macOS-async-v1.10.3-20230507-repack.tar.gz",
             "acd1520ad105d8ef124a09c8e11a259a5dc8bdc565ad18e0e52693f9807b2477"),
    "legendary": ("https://github.com/legendary-gl/legendary/releases/download/0.21.0/legendary_macOS_arm64",
                  "28f5f7d0eb8c029679d4faaa483ec85888af17a9a75977ae9170c21d8ce3428b"),
    "nile": ("https://github.com/imLinguin/nile/releases/download/v1.2.0/nile_macOS_arm64",
             "6cc74eb19117c8c309b0b94657e1e267642a3b4840d7386a133dcf6f3bffeab0"),
    # Highball's arm64-wine11.18-r1 (highball/spike/engines/arm64-wine11.18-r1.json)
    "arm64": ("https://github.com/gauthierpiarrette/highball-engine/releases/download/engine-arm64-wine-11.18-20261015T181931Z-arm64-r1/engine-arm64-wine-11.18-20261015T181931Z-arm64-r1.tar.gz",
              "01dd2f619367968bfdd38d41042a24704c99811be5c08fc219f87c63fdb19fb0"),
    "arm64-moltenvk": ("https://github.com/gauthierpiarrette/highball-engine/releases/download/moltenvk-arm64-1.4.2-20261015T181815Z-arm64-r1/moltenvk-arm64-1.4.2-20261015T181815Z-arm64-r1.tar.gz",
                       "feaab38ab4a991f145f4db10e922d247e25c5722e0873a9285ba1cb477d18496"),
    "arm64-renderers": ("https://github.com/gauthierpiarrette/highball-engine/releases/download/renderers-arm64-20261015T181326Z-arm64-r1/renderers-arm64-20261015T181326Z-arm64-r1.tar.gz",
                        "9476a69f2b4fc63c4da25888e1d36a41e5f1884f7c39809e1c03c1c577e15136"),
}
D3DMETAL_LICENSE = ("D3DMetal is Apple's, from the Game Porting Toolkit. Apple's license allows non-commercial use only, "
                    "to develop, test or evaluate games on Apple hardware, and forbids modifying or redistributing it.")

CATALOG = {
    "Steam": {"url": "https://cdn.cloudflare.steamstatic.com/client/installer/SteamSetup.exe", "file": "SteamSetup.exe", "engine": "wine"},
    "Epic Games Launcher": {"url": "https://launcher-public-service-prod06.ol.epicgames.com/launcher/api/installer/download/EpicGamesLauncherInstaller.msi",
                            "file": "EpicGamesLauncherInstaller.msi", "engine": "wine"},
    "Battle.net": {"url": "https://www.battle.net/download/getInstallerForGame?os=win&gameProgram=BATTLENET_APP&version=Live",
                   "file": "Battle.net-Setup.exe", "engine": "wine"},
    "Firefox": {"url": "https://download.mozilla.org/?product=firefox-latest&os=win64&lang=en-US", "file": "FirefoxSetup.exe", "engine": "wine"},
    "7-Zip": {"url": "https://www.7-zip.org/a/7z2409-x64.exe", "file": "7z2409-x64.exe", "args": ["/S"]},
    "Visual C++ 2015-2022 runtime": {"tricks": ["vcrun2022"]},
    ".NET Framework 4.8": {"tricks": ["dotnet48"]},
    "DirectX 9 extras (d3dx9)": {"tricks": ["d3dx9"]},
    "Microsoft core fonts": {"tricks": ["corefonts"]},
}


def cfg(name):
    f = bottle(name) / "portal.json"
    return json.loads(f.read_text()) if f.exists() else {"engine": "gptk"}  # pre-engine bottles were GPTK


def set_cfg(name, **values):
    (bottle(name) / "portal.json").write_text(json.dumps({**cfg(name), **values}))


def engine(name):
    return cfg(name)["engine"]


def set_engine(name, eng):
    if eng not in ENGINES:
        sys.exit(f"unknown engine {eng!r}; choose from: {', '.join(ENGINES)}")
    if (bottle(name) / "portal.json").exists():
        old = engine(name)
        if (eng == "arm64") != (old == "arm64") and (bottle(name) / "system.reg").exists():
            sys.exit(f"{name} was set up by {ENGINE_NAMES[old]}; bottles don't move between the native engine and the "
                     f"Intel ones. Make a new bottle with the {eng} engine (python3 portal.py copy-games can bring games over).")
        if eng != "arm64" and old != "arm64" and ENGINE_AGE[eng] < ENGINE_AGE[old] and (bottle(name) / "system.reg").exists():
            sys.exit(f"{name} has been upgraded by {ENGINE_NAMES[old]}; the older Wine in {ENGINE_NAMES[eng]} can't open it "
                     f"reliably. Make a new bottle with the {eng} engine instead.")
        kill(name)  # stop the old engine's wineserver before the other one touches the bottle
    set_cfg(name, engine=eng)
    if eng == "wine10" and "sync" not in cfg(name) and steam_exe(name, "steam.exe"):
        set_cfg(name, sync="none")  # Steam's window hangs under msync/esync on this Wine
    if graphics(name) == "dxvk" and eng == "wine":
        set_graphics(name, "dxvk")


def graphics(name):
    """The bottle's graphics layer: its setting if this engine has it, else the engine's default."""
    choices = GRAPHICS[engine(name)]
    return cfg(name).get("graphics") if cfg(name).get("graphics") in choices else choices[0]


def set_graphics(name, layer):
    eng = engine(name)
    if layer not in GRAPHICS[eng]:
        sys.exit(f"{ENGINE_NAMES[eng]} can use: {', '.join(GRAPHICS[eng])}"
                 + ("; DXMT and DXVK need the wine10 engine (python3 portal.py engine NAME wine10)" if eng == "gptk" else ""))
    if layer == "d3dmetal" and eng == "wine10" and not d3dmetal_accepted():
        sys.exit("D3DMetal needs Apple's license accepted first: python3 portal.py accept-d3dmetal")
    if eng == "wine":  # DXVK's DLLs sit in the bottle; the registry picks them or Wine's own, and a game can differ
        if layer == "dxvk":
            install_dxvk(name)
        dll_overrides(name, r"HKCU\Software\Wine\DllOverrides", layer)
    set_cfg(name, graphics=layer)
    return layer  # takes effect for programs started after this


def reg(name, *args):
    return subprocess.run([wine(name), "reg", *args], env=env(name), capture_output=True, text=True)


def dll_overrides(name, key, layer):
    """Wine 11 engine: Direct3D 10/11 from DXVK's DLLs in the bottle (dxvk), Wine's own (wined3d) or, for a game's
    key, whatever the bottle uses (None). Registry, not WINEDLLOVERRIDES: the environment would beat per-game keys."""
    for dll in ("d3d11", "d3d10core"):
        if layer is None:
            reg(name, "delete", key, "/v", dll, "/f")
        else:
            reg(name, "add", key, "/v", dll, "/t", "REG_SZ", "/d", "native,builtin" if layer == "dxvk" else "builtin", "/f")


DISPLAY = {"standard": ("n", 96), "retina": ("y", 192), "compact": ("y", 144)}  # Mac driver RetinaMode, Windows DPI


def display(name, mode=None):
    """Retina mode renders at the screen's full resolution (sharp, slower); its DPI keeps text a normal size.
    Restart the bottle's programs afterwards."""
    if mode:
        if mode not in DISPLAY:
            sys.exit(f"display: use {', '.join(DISPLAY)}")
        retina, dpi = DISPLAY[mode]
        reg(name, "add", r"HKCU\Software\Wine\Mac Driver", "/v", "RetinaMode", "/t", "REG_SZ", "/d", retina, "/f")
        reg(name, "add", r"HKCU\Control Panel\Desktop", "/v", "LogPixels", "/t", "REG_DWORD", "/d", str(dpi), "/f")
        set_cfg(name, display=mode)
    return cfg(name).get("display", "standard")


def program_exe(name, target):
    """The .exe a library entry starts (a shortcut's target), whose file name Wine's per-program settings key on."""
    if str(target).lower().endswith(".lnk"):
        target = lnk_target(target) or target
    return Path(str(target).replace("\\", "/")).name


def game_settings(name, target):
    return cfg(name).get("games", {}).get(program_exe(name, target).lower(), {})


def set_game(name, target, setting=None, value=None):
    """Per-game settings, keyed on the program's .exe so they also apply when Steam or a launcher starts it:
    graphics (a layer, or default for the bottle's) and mouse (enable, force or disable warping the pointer:
    try force for games whose camera spins or that lose the mouse; default resets)."""
    exe = program_exe(name, target)
    games = cfg(name).get("games", {})
    mine = games.get(exe.lower(), {})
    if not setting:
        return mine
    app = rf"HKCU\Software\Wine\AppDefaults\{exe}"
    if setting == "graphics":
        if value != "default" and value not in GRAPHICS[engine(name)]:
            sys.exit(f"graphics: {', '.join(GRAPHICS[engine(name)])} or default")
        if value == "d3dmetal" and engine(name) == "wine10" and not d3dmetal_accepted():
            sys.exit("D3DMetal needs Apple's license accepted first: python3 portal.py accept-d3dmetal")
        if engine(name) == "wine":
            if value == "dxvk":
                install_dxvk(name)
            dll_overrides(name, app + r"\DllOverrides", None if value == "default" else value)
    elif setting == "mouse":
        if value not in ("enable", "force", "disable", "default"):
            sys.exit("mouse: enable, force, disable or default")
        if value == "default":
            reg(name, "delete", app + r"\DirectInput", "/v", "MouseWarpOverride", "/f")
        else:
            reg(name, "add", app + r"\DirectInput", "/v", "MouseWarpOverride", "/t", "REG_SZ", "/d", value, "/f")
    else:
        sys.exit("game settings: graphics or mouse")
    if value == "default":
        mine.pop(setting, None)
    else:
        mine[setting] = value
    games[exe.lower()] = mine
    set_cfg(name, games={k: v for k, v in games.items() if v})
    return mine


def d3dmetal_accepted():
    f = DATA / "licenses.json"
    return f.exists() and json.loads(f.read_text()).get("d3dmetal")


def accept_d3dmetal(ask=True):
    if ask:
        print(D3DMETAL_LICENSE, f"\nFull text: {SIK / 'Frameworks/renderer/d3dmetal/License.rtf'}")
        if input("Type yes to accept: ").strip().lower() != "yes":
            sys.exit("not accepted")
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "licenses.json").write_text(json.dumps({"d3dmetal": time.strftime("%Y-%m-%d")}))


def sync_mode(name, mode=None):
    """wine10 only. msync is fastest for games, but Steam's own window hangs under msync/esync on this Wine
    (Highball's Steam recipe), so bottles that run Steam's window use none. Restart the bottle's programs after."""
    if engine(name) != "wine10":
        sys.exit("sync modes apply to wine10 bottles")
    if mode:
        if mode not in ("msync", "esync", "none"):
            sys.exit("sync: use msync, esync or none")
        kill(name)  # the wineserver fixes the mode when it starts
        set_cfg(name, sync=mode)
    return cfg(name).get("sync", "msync")


def wine(name):
    eng = engine(name)
    if eng == "arm64":
        link_wineloader()  # Highball.app may have moved or updated since the last launch
    p = ENGINES[eng]
    if not p.exists():
        sys.exit(f"{ENGINE_NAMES[eng]} isn't installed. Run: python3 portal.py "
                 + ("get-engine arm64" if eng == "arm64" else "get-engine wine10" if eng == "wine10" else "setup"))
    return str(p)


def wineloader():
    """The signed Wine loader in Highball.app, or None."""
    return next((p for p in WINELOADER_PATHS if p.is_file()), None)


def arm64_missing():
    """Why the native engine can't run on this Mac, or None."""
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return "the native engine is for Apple Silicon Macs"
    if tuple(int(x) for x in (platform.mac_ver()[0] or "0").split(".")[:1]) < (15,):
        return "the native engine needs macOS 15 or later"
    if not wineloader():
        return ("the native engine needs Highball's signed Wine loader: install Highball (gethighball.com), "
                "or set WINDOWSPORTAL_WINELOADER to a signed loader")
    return None


def link_wineloader():
    """Points the engine's loaders at the signed one: lib/wine/aarch64-unix/wine -> the helper, bin/wine -> that.
    The helper finds ntdll.so beside each symlink it was started through, so nothing is copied into Highball.app.
    The engine's own unsigned loaders are kept as *.unsigned."""
    helper = wineloader()
    if not helper or not (ARM / "engine").is_dir():
        return
    for link, target in ((ARM / "engine/lib/wine/aarch64-unix/wine", str(helper)),
                         (ARM / "engine/bin/wine", "../lib/wine/aarch64-unix/wine")):
        if link.is_symlink():
            if os.readlink(link) == target:
                continue
            link.unlink()
        elif link.exists():
            link.replace(link.with_name("wine.unsigned"))
        link.symlink_to(target)


def bottle(name, exists=True):
    if not name or "/" in name or name.startswith("."):
        sys.exit(f"bad bottle name: {name!r}")
    if exists and not (HOME / name).is_dir():
        sys.exit(f"no bottle {name}")
    return HOME / name


def wine_env(name, target=None):
    # Speed/memory: no debug logging, esync/msync instead of wineserver round-trips for every lock,
    # no winemenubuilder (it spawns per install and litters ~/.local), AVX advertised to Rosetta for games.
    extra, overrides = engine_env(name, target)
    return {"WINEPREFIX": str(bottle(name)), "WINEDEBUG": "-all", "WINEESYNC": "1", "WINEMSYNC": "1",
            # gameoverlayrenderer: Steam's in-game overlay hangs games under Wine (Portal spun at 100% CPU, no window).
            # Steam passes its environment to the games it launches, so this covers them too.
            "WINEDLLOVERRIDES": ";".join([os.environ.get("WINEDLLOVERRIDES", "winemenubuilder.exe=d;gameoverlayrenderer=d"),
                                          *overrides]),
            **({} if engine(name) == "arm64" else {"ROSETTA_ADVERTISE_AVX": "1"}), **extra}


def engine_env(name, target=None):
    """({env}, [DLL overrides]) for the bottle's engine and graphics layer, or the game's own layer on wine10."""
    eng, env, overrides = engine(name), {}, []
    layer = (game_settings(name, target).get("graphics") if target and eng == "wine10" else None) or graphics(name)
    if eng == "wine10":
        fw = SIK / "Frameworks"
        gst = fw / "GStreamer.framework/Versions/1.0/lib"
        env = {"DYLD_FALLBACK_LIBRARY_PATH": f"{fw}:{gst}", "DYLD_FALLBACK_FRAMEWORK_PATH": str(fw),
               "GST_PLUGIN_PATH": f"{gst}/gstreamer-1.0",
               "CX_FWD_COMPAT_GL_CTX": "1"}  # GL 3.2+ core contexts without the forward-compatible bit work too
        mode = cfg(name).get("sync", "msync")
        env.update(WINEMSYNC="1" if mode == "msync" else "0", WINEESYNC="1" if mode == "esync" else "0")
        # Layers are folders of DLLs this Wine searches before its own. d9vk (DXVK's Direct3D 9) rides along with the
        # Metal layers, which have no Direct3D 9 of their own; 64-bit-only D3DMetal falls back to DXMT for 32-bit games.
        layers = {"dxmt": ["dxmt", "d9vk"], "d3dmetal": ["d3dmetal", "dxmt", "d9vk"], "dxvk": ["d9vk", "dxvk"]}.get(layer, [])
        if layers:
            env["WINEDLLPATH_PREPEND"] = ":".join(str(fw / "renderer" / l / "wine") for l in layers)
        if layer == "d3dmetal":
            ext = fw / "renderer/d3dmetal/external"
            env.update(CX_D3DMETALPATH=str(ext), DYLD_FALLBACK_LIBRARY_PATH=f"{env['DYLD_FALLBACK_LIBRARY_PATH']}:{ext}",
                       DYLD_FALLBACK_FRAMEWORK_PATH=f"{fw}:{ext}")
        if layer == "dxvk":
            overrides.append("dxgi,d3d9,d3d10core,d3d11=n,b")
    elif eng == "arm64":
        env = {"GST_PLUGIN_PATH": str(ARM / "frameworks/GStreamer.framework/Versions/1.0/lib/gstreamer-1.0"),
               "MVK_CONFIG_SHADER_SOURCE_COMPRESSION_ALGORITHM": "1",  # the shader cache it keeps stays small
               "MVK_CONFIG_RESUME_LOST_DEVICE": "1", "DXVK_RELAX_FEATURES": "1"}
        if layer in ("vkd3d", "dxvk"):
            env["WINEDLLPATH_PREPEND"] = str(ARM / "renderers" / layer / "wine")
        if layer == "vkd3d":  # MoltenVK reports neither feature level nor shader model honestly: declare D3DMetal's
            overrides.append("dxgi,d3d11,d3d10core,d3d12,d3d12core=n,b")
            env.update(VKD3D_RELAX_DEVICE_CAPS="1", VKD3D_FEATURE_LEVEL="12_0", VKD3D_SHADER_MODEL="6_6",
                       VKD3D_SHADER_CACHE_PATH="C:\\vkd3d-cache\\arm64-wine11.18-r1")  # per engine build, in the bottle
        elif layer == "dxvk":
            overrides.append("dxgi,d3d10core,d3d11=n,b")  # Direct3D 9 stays Wine's own on this line
    return env, overrides


def fetch(what):
    """Downloads a PINNED file and checks its SHA-256."""
    url, sha = PINNED[what]
    f = download(url, Path(urllib.parse.urlparse(url).path).name)
    h = hashlib.sha256()
    with open(f, "rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    if h.hexdigest() != sha:
        f.unlink()
        sys.exit(f"{Path(f).name} failed its checksum; deleted it, try again")
    return f


def get_engine(eng="wine10"):
    """Installs the wine10 engine (Sikarugir's Wine 10 and its runtime: MoltenVK, GStreamer, graphics layers), or the
    native arm64 preview."""
    if eng == "arm64":
        return get_arm64()
    if eng != "wine10":
        sys.exit("get-engine installs wine10 or arm64; the others come with: python3 portal.py setup")
    if ENGINES["wine10"].exists():
        return
    tmp = SIK.with_name(SIK.name + ".part")  # renamed when complete, so a half-unpacked engine never looks installed
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "Frameworks").mkdir(parents=True)
    for part, dest, only in (("wine10", tmp, []),
                             ("wine10-runtime", tmp / "Frameworks", ["--strip-components", "3", "Template-1.0.11.app/Contents/Frameworks"])):
        f = fetch(part)
        subprocess.run(["tar", "-xf", str(f), "-C", str(dest), *only], check=True)
        f.unlink()
    tmp.rename(SIK)


def get_arm64():
    if why := arm64_missing():
        sys.exit(why)
    if not ENGINES["arm64"].exists():
        tmp = ARM.with_name(ARM.name + ".part")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        for part in ("arm64", "arm64-moltenvk", "arm64-renderers"):
            f = fetch(part)
            dest = tmp / "moltenvk" if part == "arm64-moltenvk" else tmp
            dest.mkdir(exist_ok=True)
            subprocess.run(["tar", "-xf", str(f), "-C", str(dest)], check=True)
            f.unlink()
        # Highball's patched MoltenVK replaces the archive's: winevulkan opens the one in engine/lib on this line
        (tmp / "moltenvk/lib/libMoltenVK.dylib").replace(tmp / "engine/lib/libMoltenVK.dylib")
        shutil.rmtree(tmp / "moltenvk")
        for f in tmp.rglob("._*"):  # AppleDouble leftovers from the archive make GStreamer log a warning per plugin
            f.unlink()
        tmp.rename(ARM)
    link_wineloader()


def copy_games(src, dest):
    """Clones a bottle's C:\\Games into another (APFS copy-on-write: instant, no extra disk). For moving to the native
    engine, whose bottles can't be converted. Installers and Steam libraries still need setting up in the new one."""
    s, d = bottle(src) / "drive_c/Games", bottle(dest) / "drive_c/Games"
    if not s.is_dir():
        sys.exit(f"{src} has no C:\\Games")
    d.mkdir(parents=True, exist_ok=True)
    for game in s.iterdir():
        if not (d / game.name).exists():
            subprocess.run(["cp", "-cR", str(game), str(d / game.name)], check=True)
            if exe := main_exe(d / game.name):
                add_program(dest, str(exe), game.name)
    return sorted(p.name for p in d.iterdir())


def install_dxvk(name):
    """Puts DXVK-macOS's DLLs in a Wine 11 bottle; engine_env decides per launch whether they're used."""
    src = DATA / "engines/dxvk-macos-1.10.3"
    if not src.exists():
        f = fetch("dxvk")
        tmp = src.with_name(src.name + ".part")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        subprocess.run(["tar", "-xf", str(f), "-C", str(tmp), "--strip-components", "1"], check=True)
        f.unlink()
        tmp.rename(src)
    for arch, sysdir in (("x64", "system32"), ("x32", "syswow64")):
        for dll in (src / arch).glob("*.dll"):
            shutil.copy(dll, bottle(name) / "drive_c/windows" / sysdir / dll.name)


def env(name, target=None):
    return {**os.environ, **wine_env(name, target)}


def setup():
    # Both engines are Intel builds; without Rosetta every wine call fails with "bad CPU type".
    if platform.machine() == "arm64" and subprocess.run(["arch", "-x86_64", "/usr/bin/true"], capture_output=True).returncode:
        subprocess.run(["softwareupdate", "--install-rosetta", "--agree-to-license"], check=True)
    # Homebrew's own Wine casks were disabled 2026-09-01 (Gatekeeper); Gcenx's GPTK build still installs.
    subprocess.run(["brew", "tap", "gcenx/wine"], check=True)
    subprocess.run(["brew", "trust", "gcenx/wine"], check=True)
    subprocess.run(["brew", "install", "--cask", "game-porting-toolkit"], check=True)
    subprocess.run(["brew", "install", "winetricks"], check=True)
    if not ENGINES["wine"].exists():
        tarball = fetch("wine")
        dest = DATA / f"engines/wine-{WINE_VERSION}"
        dest.mkdir(parents=True, exist_ok=True)
        subprocess.run(["tar", "-xf", str(tarball), "-C", str(dest)], check=True)
        tarball.unlink()
    get_engine("wine10")


def bottles():
    return sorted(p.name for p in HOME.iterdir() if p.is_dir()) if HOME.exists() else []


def new(name, winver="win10", eng=None):
    p = bottle(name, exists=False)
    eng = eng or next((e for e in ("wine10", "wine") if ENGINES[e].exists()), "gptk")
    if p.exists():
        sys.exit(f"bottle {name} already exists")
    if not ENGINES.get(eng, Path("/nonexistent")).exists():
        sys.exit(f"engine {eng!r} isn't available; choose from: {', '.join(e for e, p in ENGINES.items() if p.exists())}")
    p.mkdir(parents=True)
    set_engine(name, eng)
    w = wine(name)
    subprocess.run([w, "wineboot", "--init"], env=env(name), check=True)
    subprocess.run([w, "winecfg", "-v", winver], env=env(name), check=True)
    keys(name, True)


MAC_KEYS = ("LeftCommandIsCtrl", "RightCommandIsCtrl", "LeftOptionIsAlt", "RightOptionIsAlt")


def keys(name, on=None):
    """Shows or sets whether Command acts as Ctrl (so ⌘C/⌘V/⌘A work) and Option as Alt.
    Wine's default makes Command act as Alt; Option is remapped too, else Alt is unreachable."""
    k = r"HKCU\Software\Wine\Mac Driver"
    if on is None:
        out = subprocess.run([wine(name), "reg", "query", k, "/v", MAC_KEYS[0]], env=env(name), capture_output=True, text=True).stdout
        return "on" if re.search(r"REG_SZ\s+y", out) else "off"
    if isinstance(on, str):
        on = {"on": True, "off": False}.get(on) if on in ("on", "off") else sys.exit("keys: use on or off")
    for v in MAC_KEYS:  # REG_SZ "y"/"n": the Mac driver ignores a DWORD here
        subprocess.run([wine(name), "reg", "add", k, "/v", v, "/t", "REG_SZ", "/d", "y" if on else "n", "/f"],
                       env=env(name), check=True, capture_output=True)
    return "on" if on else "off"  # applies to programs started after this


def winver(name, ver=None):
    """Shows or sets the Windows version the bottle reports (e.g. win10, win11, win7)."""
    if ver:
        subprocess.run([wine(name), "winecfg", "-v", ver], env=env(name), check=True)
        return ver
    # Ask Wine, not system.reg: the file is only rewritten when the bottle's wineserver exits.
    out = subprocess.run([wine(name), "reg", "query", r"HKLM\Software\Microsoft\Windows NT\CurrentVersion", "/v", "ProductName"],
                         env=env(name), capture_output=True, text=True).stdout
    return next((l.split("REG_SZ", 1)[1].strip() for l in out.splitlines() if "REG_SZ" in l), "unknown")


# Steam's Chromium UI paints from its GPU process into a window the browser process owns, and Wine's Mac
# driver never shows another process's drawing, so the window stays black. This stand-in for
# steamwebhelper.exe (steamwebhelper.c; x86_64-w64-mingw32-gcc -Os -s -nostdlib -e start -mwindows
# steamwebhelper.c -lkernel32) runs the real one as steamwebhelper_real.exe with --in-process-gpu.
WEBHELPER = zlib.decompress(base64.b64decode(
    "eNrtV0Fs21QY/u22Udc2XYDlwAHhVUaUw0wzBJomwVqStA/I0mjJFmmqhJ3EaTwldmQ7Img9AN0mWZWlCiRuu3DlghDS2opDxATdDpOgSJu0yx"
    "AHEBqg0R1WcTH/83tZ6ehAiMPQli96/t7//b//9/s9Pzs+enIZ+gCgH1sQAKwAwyT8M97BNvr02ih8tufK/hUhc2V/oWY4UtO25m2tIZU107Rc"
    "qaRLdsuUDFNKzealhlXRlWh0SOY5cmmAyrkIfLDvm1PdvLdAEYdF8fmwqCFanAAQA9awNAF4X2R1UwxQg6IphOLpNHWraEhMj3Wzx+6xd3SBni"
    "KJf7InAEbgv2MZ89b+xq+4ettFDseO8QXp3xmDV6IqdkVzNTb34aXR+MGdcbh2k0qTxY3wawjjhnaJa7O4WHfRadzILnElxwmHFHFKc/e9HzqK"
    "wfKF16GytYDRv+aDHv4XOF48kSfv/tzGlSL+i78eEWBqhW63xGXibQbx8zkB9fjVveheevkCWl6H+JnpreBaEG9Sp3exunhorCVVl5IiWbwoVs"
    "923Eh1cWus9Qvx89Qke9PXb0ard/puBG6Ehty8Tfzo2SOY0tusrg+8hb0xCK7hAFk23Gk6nB9V0YGydx37Bdb342XmS4V2YgPr9D+Xv6NPr/il"
    "WQFW6YNlanUZjxn/TOgg3peJztoe7N3+mHg/EX9BXlg/I9/iO4idl+isPol2OnEZg/yUrKYTHeL9RryUTKjdxqG/foUmS8mTic46KjVg5iF6mE"
    "BlnN7ryJIQljOFacnSU6/SqqiCE5MmSwVZxSKC+BOhNyPXgvgk76prAcW2TfyCPIcJ51jCQdRRngu+Xb6L4JkxVCk/zlnkvJll/D3nDc5fcP6U"
    "80ec3+f8Hmc75N4OebjxJtiggwZ1UJDb2OhmpBvjAP4MMPHYxBgLyuhz8HcA5lFp8fNnksnD0vhM9vhzUuIl5aAycU/+gON+dg8PGPjiv/AY9N"
    "7IjyiE4QgMC/hXe6JPFZtCrjcjjxbGVWH7UVASwu+U3bDF9X0a43HOhzkTzic5Nzmf4/wh5084f8V5QxMeyDjPwpTjGPNmzrbKuuMUrNet0mzp"
    "lF7Gj7AfIWnrmqvflYoAv3ONx6OyIKTbhsttuCPM6G7SajQ0s5IxTL0IqogKDUniJ283DM5T9ahVadX1aaOuZ7UGhsIP/cd0p9XQCzUcpAJwYi"
    "Cvu6+ZVctuaK5hmdvFDUaKmuFOW3beMOfrOlerkbrj2mWNVmqxfvPtYvd79t+0N9LHsunMCweVSr3e2x0PP/4AUWqD+g=="))


def steam_exe(name, target):
    """The bottle's steam.exe if target launches Steam (its shortcut or exe), else None."""
    exe = bottle(name) / "drive_c/Program Files (x86)/Steam/steam.exe"
    return exe if Path(target).stem.lower() == "steam" and exe.exists() else None


def fix_steam(name):
    """Puts the webhelper stand-in in place; Steam updates overwrite it, so this runs on every launch."""
    d = bottle(name) / "drive_c/Program Files (x86)/Steam/bin/cef/cef.win64"
    if (w := d / "steamwebhelper.exe").exists() and w.read_bytes() != WEBHELPER:
        w.replace(d / "steamwebhelper_real.exe")
        w.write_bytes(WEBHELPER)


def steam_appid(name, target):
    """Steam's app id if target is a game under the bottle's Steam library, else None."""
    p = str(Path(target).resolve())
    return next((a for a, _, folder, _ in steam_games(name) if p.startswith(f"{folder.resolve()}/")), None) \
        if "/steamapps/common/" in p else None


def run(name, exe, *args, wait=True):
    if hit := launcher_app_of(name, exe):  # Epic and Amazon games need a fresh login token or their store's variables
        proc = (epic_launch if hit[0] == "epic" else amazon_launch)(name, hit[1], *args)
        return proc.wait() if wait else proc
    w, game = wine(name), exe
    if appid := steam_appid(name, exe):  # Steam games launch through Steam: it adds their launch options and DRM
        exe, args = "steam.exe", ("-applaunch", appid, *args)
    if steam := steam_exe(name, exe):  # -noverifyfiles: else Steam "repairs" the stand-in at startup
        fix_steam(name)
        exe, args = str(steam), ("-noverifyfiles", *args)
    low = exe.lower()
    cmd = ([w, "msiexec", "/i", exe] if low.endswith(".msi") else
           [w, "start", "/unix", exe] if low.endswith(".lnk") else [w, exe])
    # A game's own graphics layer (wine10) rides in the environment: through Steam it applies if this starts Steam.
    proc = subprocess.Popen([*cmd, *args], env=env(name, game), cwd=Path(exe).parent if os.path.exists(exe) else None)
    return proc.wait() if wait else proc


def tricks(name, *verbs):
    bottle(name)
    wt = shutil.which("winetricks") or sys.exit("winetricks not found. Run: python3 portal.py setup")
    subprocess.run([wt, *(verbs or ["--gui"])], env={**env(name), "WINE": wine(name)})


def kill(name):
    """Stops everything running in a bottle: wineserver -k, then whatever outlived it (a hung Steam webhelper, a
    game stuck at exit keeps the Mac awake and the battery draining)."""
    try:
        w = wine(name)
    except SystemExit:
        return  # engine not installed, so nothing of this bottle can be running
    try:
        subprocess.run([str(Path(w).with_name("wineserver")), "-k"], env=env(name), timeout=5)
    except subprocess.TimeoutExpired:
        pass
    for sig, wait in ((15, 2), (9, 1)):  # SIGTERM, then SIGKILL
        if not (left := bottle_pids(name)):
            return
        for pid in left:
            try:
                os.kill(pid, sig)
            except OSError:
                pass
        time.sleep(wait)


def bottle_pids(name):
    """Processes started with this bottle's WINEPREFIX, from ps -E (the environment, readable for your own)."""
    tag = f"WINEPREFIX={bottle(name)}"
    out = subprocess.run(["ps", "-axwwE", "-o", "pid=,command="], capture_output=True, text=True).stdout
    return [int(line.split(None, 1)[0]) for line in out.splitlines()
            if re.search(re.escape(tag) + r"(\s|$)", line) and int(line.split(None, 1)[0]) != os.getpid()]


def steam_repair(name):
    """Mac Wine Launcher's Steam recovery: stop everything, clear the web views' cache, drop a steam.cfg that blocks
    Steam's self-update, start Steam and check its web helper comes up."""
    steam = steam_exe(name, "steam.exe") or sys.exit(f"Steam isn't installed in {name}")
    kill(name)
    for cache in [*bottle(name).glob("drive_c/users/*/AppData/Local/Steam/htmlcache"), steam.parent / "config/htmlcache"]:
        shutil.rmtree(cache, ignore_errors=True)
    if (cfgfile := steam.parent / "steam.cfg").exists():
        keep = [l for l in cfgfile.read_text(errors="replace").splitlines()
                if l.strip().lower() != "bootstrapperinhibitall=enable"]
        if any(l.strip() for l in keep):
            cfgfile.write_text("\n".join(keep) + "\n")
        else:
            cfgfile.rename(cfgfile.with_name("steam.cfg.disabled-by-windows-portal"))
    run(name, str(steam), wait=False)
    for _ in range(90):  # its first start after an update can take a while under Rosetta
        time.sleep(2)
        out = subprocess.run([wine(name), "tasklist"], env=env(name), capture_output=True, text=True).stdout
        if "steamwebhelper" in out.lower():
            return "Steam is up"
    return ("Steam's window didn't come up within 3 minutes. If it's still updating, give it time; "
            + ("on wine10, try: python3 portal.py sync " + name + " none" if engine(name) == "wine10" and sync_mode(name) != "none"
               else "otherwise run the repair again."))


def programs(name):
    """{display name: .lnk/.exe path}: the bottle's Start Menu plus programs added by hand."""
    p, users = bottle(name), bottle(name) / "drive_c/users"
    dirs = [p / "drive_c/ProgramData/Microsoft/Windows/Start Menu",
            *users.glob("*/AppData/Roaming/Microsoft/Windows/Start Menu"), *users.glob("*/Desktop")]
    # Wine symlinks Desktop to the Mac's ~/Desktop; skip it so we don't crawl the user's files.
    found = {l.stem: str(l) for d in dirs if d.is_dir() and not d.is_symlink()
             for l in sorted(d.rglob("*.lnk")) if "uninstall" not in l.stem.lower()}
    return {**found, **{t: p for t, p in library().get(name, {}).items() if os.path.exists(p)}}  # skip moved/deleted


def library():
    f = DATA / "library.json"
    return json.loads(f.read_text()) if f.exists() else {}


def save_library(lib):
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "library.json").write_text(json.dumps(lib, indent=1))


def add_program(name, path, title=None):
    """Adds a program that has no Start Menu shortcut (e.g. a portable game) to the library."""
    bottle(name)
    lib = library()
    lib.setdefault(name, {})[title or Path(path).stem] = str(Path(path).resolve())
    save_library(lib)


def remove_program(name, title):
    lib = library()
    lib.get(name, {}).pop(title, None)
    save_library(lib)


def catalog():
    c = dict(CATALOG)
    if (DATA / "catalog.json").exists():
        c.update(json.loads((DATA / "catalog.json").read_text()))
    return c


def download(url, file):
    # ponytail: cached forever, delete ~/Library/Caches/WindowsPortal to pick up newer installers.
    CACHE.mkdir(parents=True, exist_ok=True)
    dest = CACHE / Path(file).name
    if not dest.exists():
        part = dest.with_suffix(".part")
        have = part.stat().st_size if part.exists() else 0  # an interrupted download picks up where it stopped
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", **({"Range": f"bytes={have}-"} if have else {})})
        try:
            with urllib.request.urlopen(req) as r, open(part, "ab" if r.status == 206 else "wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)  # streamed, never the whole installer in memory
        except urllib.error.HTTPError as e:
            if e.code != 416:  # 416: the .part already holds the whole file
                raise
        part.rename(dest)
    return dest


def install(name, item):
    """Installs a catalog ITEM, or a local .exe/.msi/archive if ITEM is a path."""
    if os.path.exists(item):
        return install_file(name, item)
    e = catalog().get(item) or sys.exit(f"unknown item {item!r}; see: python3 portal.py catalog")
    if e.get("engine") and e["engine"] != engine(name):  # modern launchers crash on GPTK's Wine 7.7
        sys.exit(f"{item} needs a {ENGINE_NAMES[e['engine']]} bottle; {name} uses {ENGINE_NAMES[engine(name)]}.")
    before = programs(name)
    if e.get("tricks"):
        tricks(name, "-q", *e["tricks"])
    if e.get("url"):
        run(name, str(download(e["url"], e.get("file") or "setup.exe")), *e.get("args", []))
    if item == "Steam" and engine(name) == "wine10" and "sync" not in cfg(name):
        sync_mode(name, "none")  # Steam's window hangs under msync/esync on this Wine
        print(f"{name}: sync set to none for Steam's window; python3 portal.py sync {name} msync trades that for game speed")
    if item == "Steam" and steam_exe(name, "steam.exe"):  # its installer starts Steam without the black-window fix
        kill(name)
        run(name, "steam.exe", wait=False)
    return register_new(name, before)


ARCHIVES = (".zip", ".7z", ".rar", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".cab", ".iso")
NOT_MAIN = ("unins", "crash", "redist", "vc_redist", "dxsetup", "dotnet", "helper", "update", "report", "prereq", "anticheat")


def main_exe(folder):
    """Best guess at a folder's main program: shallowest, then biggest, .exe that isn't a helper."""
    folder = Path(folder)
    exes = sorted((p for p in folder.rglob("*.exe") if p.is_file() and not any(w in p.stem.lower() for w in NOT_MAIN)),
                  key=lambda p: (len(p.relative_to(folder).parts), -p.stat().st_size))
    return exes[0] if exes else None


def register_new(name, before, fallback=None, title=None):
    """Adds Mac apps for new Start Menu entries; with none, puts `fallback` (a portable exe) in the library."""
    added = {k: v for k, v in programs(name).items() if k not in before}
    if not added and fallback:
        title = title or Path(fallback).stem
        add_program(name, fallback, title)
        added = {title: str(Path(fallback).resolve())}
    for title, target in added.items():
        print("Mac app:", mac_app(name, target, title))
    return added


def install_file(name, path, title=None):
    """Runs an installer, or unpacks an archive into C:\\Games and installs/registers what's inside."""
    bottle(name)
    before, low = programs(name), path.lower()
    if low.endswith((".exe", ".msi", ".bat")):
        run(name, path)
        # ponytail: an exe that makes no shortcut is assumed portable; an installer that silently
        # skips shortcuts lands in the library as its setup.exe, Remove + Add Program fixes it.
        return register_new(name, before, fallback=None if low.endswith(".msi") else path, title=title)
    if not low.endswith(ARCHIVES):
        sys.exit(f"don't know how to install {Path(path).name}; use an .exe, .msi or archive")
    stem = Path(path).name
    for ext in ARCHIVES:
        stem = stem.removesuffix(ext).removesuffix(ext.upper())
    dest = bottle(name) / "drive_c/Games" / stem
    dest.mkdir(parents=True, exist_ok=True)
    # macOS tar is libarchive: zip, 7z, rar, cab, iso, tar.*; it refuses absolute and ../ paths.
    if subprocess.run(["tar", "-xf", path, "-C", str(dest)]).returncode:
        sys.exit(f"couldn't extract {Path(path).name}")
    exes = sorted((p for p in dest.rglob("*") if p.suffix.lower() in (".exe", ".msi") and p.is_file()),
                  key=lambda p: (len(p.relative_to(dest).parts), -p.stat().st_size))
    setup = next((p for p in exes if any(w in p.stem.lower() for w in ("setup", "install"))
                  and not any(w in p.stem.lower() for w in NOT_MAIN)), None)
    if setup and len(setup.relative_to(dest).parts) <= 2:
        run(name, str(setup))
        return register_new(name, before)
    main = main_exe(dest)
    if not main:
        sys.exit(f"no program found in {Path(path).name}; files are in {dest}")
    return register_new(name, before, fallback=str(main), title=title or stem)


STEAM_BOTTLE = "steam-gptk"  # GPTK bottle that Steam games get cloned into, for DirectX 12 / D3DMetal


def vdf_pairs(path):
    # ponytail: flat "key" "value" scan, enough for appmanifest/libraryfolders fields we read; not a real VDF parser.
    return re.findall(r'"([^"]*)"\s+"([^"]*)"', Path(path).read_text(errors="replace"))


def steam_games(name):
    """[(appid, title, game folder, last updated)] for games Steam has fully installed in a bottle."""
    root = bottle(name) / "drive_c/Program Files (x86)/Steam/steamapps"
    libs = {root.resolve()}  # resolve: C: is reachable as both drive_c and dosdevices/c:
    if (root / "libraryfolders.vdf").exists():
        libs |= {(win_to_mac(name, v.replace("\\\\", "\\")) / "steamapps").resolve() for k, v in vdf_pairs(root / "libraryfolders.vdf") if k == "path"}
    games = []
    for lib in libs:
        for acf in lib.glob("appmanifest_*.acf"):
            d = {}
            for k, v in vdf_pairs(acf):
                d.setdefault(k, v)  # top-level keys come first; nested sections may reuse names
            if int(d.get("StateFlags", 0)) & 4 and not d.get("name", "").startswith(("Steamworks", "Steam Linux", "Proton")):
                games.append((d["appid"], d["name"], lib / "common" / d["installdir"], d.get("LastUpdated", "")))
    return games


def uses_dx12(folder):
    """DirectX 12 games need GPTK's D3DMetal; everything else runs better on the newer Wine in Steam's own bottle."""
    import mmap
    folder = Path(folder)
    if any(folder.rglob("D3D12*.dll")) or any(folder.rglob("d3d12*.dll")):  # Agility SDK shipped with the game
        return True
    for exe in folder.rglob("*.exe"):
        try:
            with open(exe, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
                if m.find(b"d3d12.dll") != -1 or m.find(b"D3D12.dll") != -1:
                    return True
        except (OSError, ValueError):  # empty or unreadable file
            pass
    return False


def unplace_steam_game(entry):
    """Undoes sync_steam's library entry, Mac app and (for GPTK) clone of one game."""
    b, title = entry.get("bottle", STEAM_BOTTLE), entry["title"]
    if (HOME / b).is_dir():
        remove_program(b, title)
        prefix = f"WINEPREFIX={shlex.quote(str(HOME / b))} "
        for app in (APPS / f"{title.replace('/', '-')}.app", APPS / f"{title.replace('/', '-')} ({b}).app"):
            if (app / "Contents/MacOS/launch").exists() and prefix in (app / "Contents/MacOS/launch").read_text():
                shutil.rmtree(app)
        if b == STEAM_BOTTLE:
            shutil.rmtree(HOME / b / "drive_c/Games" / entry["dir"], ignore_errors=True)


import threading
_sync_lock = threading.Lock()  # the GUI refreshes from worker threads; two syncs must not clone over each other


def sync_steam():
    with _sync_lock:
        return _sync_steam()


def _sync_steam():
    """Puts every game Steam installs in the library, like CrossOver's game detection. DirectX 12 games get cloned
    into the GPTK bottle (APFS copy-on-write via cp -c: instant, no extra disk until Steam updates the original);
    the rest stay in Steam's bottle and launch through Steam, so they get their launch options and DRM."""
    sources = [b for b in bottles() if b != STEAM_BOTTLE and (bottle(b) / "drive_c/Program Files (x86)/Steam/steamapps").is_dir()]
    found = {g[0]: (b, *g[1:]) for b in sources for g in steam_games(b)}
    f = DATA / "steam_sync.json"
    synced = json.loads(f.read_text()) if f.exists() else {}
    # entries without "bottle" predate DX12-only cloning: redo them
    changed = {a: g for a, g in found.items() if synced.get(a, {}).get("stamp") != g[3] or "bottle" not in synced[a]}
    gone = [a for a in synced if a not in found]
    if not changed and not gone:
        return {}
    for appid in gone:  # uninstalled in Steam
        unplace_steam_game(synced.pop(appid))
    for appid, (src, title, folder, stamp) in changed.items():  # new or updated in Steam
        if appid in synced:
            unplace_steam_game(synced[appid])
        # D3DMetal is GPTK's: DirectX 12 needs it, and Highball's database names it best for some DX11 games too.
        # A wine10 bottle has D3DMetal itself, so its games stay with its Steam.
        if engine(src) not in ("wine10", "arm64") and (uses_dx12(folder) or (compat(appid).get("game") or {}).get("renderer") == "d3dmetal"):
            if not (HOME / STEAM_BOTTLE).exists():
                if not ENGINES["gptk"].exists():
                    sys.exit("DirectX 12 games need Game Porting Toolkit; run: python3 portal.py setup")
                new(STEAM_BOTTLE, "win10", "gptk")
            where, dest = STEAM_BOTTLE, bottle(STEAM_BOTTLE) / "drive_c/Games" / folder.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.rmtree(dest, ignore_errors=True)
            if os.stat(folder).st_dev == os.stat(dest.parent).st_dev:
                subprocess.run(["cp", "-cR", str(folder), str(dest)], check=True)
                exe = main_exe(dest)
                if exe:
                    (exe.parent / "steam_appid.txt").write_text(appid)  # lets SteamAPI_Init find its app id outside Steam
            else:  # another drive: cp -c can't clone across volumes, so GPTK runs it where Steam put it
                exe = main_exe(folder)
        else:
            where, exe = src, main_exe(folder)  # the exe only supplies the icon; launching goes through Steam
        if exe:
            add_program(where, str(exe), title)
            mac_app(where, str(exe), title)
        synced[appid] = {"title": title, "dir": folder.name, "stamp": stamp, "bottle": where}
    f.write_text(json.dumps(synced, indent=1))
    return {"added or updated": [f"{found[a][1]} ({synced[a]['bottle']})" for a in changed], "removed": gone}


# Highball's open compatibility database (github.com/gauthierpiarrette/highball-db): per-game verdicts for Wine on
# Apple Silicon. Curated entries are CC0; "prediction" entries are ProtonDB-derived (ODbL), so they're labelled as such.
COMPAT_URL = "https://gethighball.com/data/steam/{}.json"
COMPAT_INDEX = "https://gethighball.com/data/games.json"
COMPAT_STATUS = {"verified-local": "Verified by Highball", "community": "Community reports say it runs",
                 "reported-upstream": "Reported working upstream", "blocked-anticheat": "Won't run: kernel anti-cheat",
                 "blocked-publisher": "Won't run: blocked by the publisher"}
RENDERERS = {"d3dmetal": "D3DMetal (the gptk engine)", "dxmt": "DXMT", "dxvk": "DXVK", "wined3d": "WineD3D",
             "vkd3d": "vkd3d-proton (DirectX 12)"}


def compat_fetch(url, file, max_age=7 * 86400, cached_only=False):
    """JSON from url cached in CACHE/compat/file; None on 404, {} when offline with nothing cached."""
    out = CACHE / "compat" / file
    fresh = out.exists() and time.time() - out.stat().st_mtime < max_age
    if fresh or cached_only:
        return json.loads(out.read_text()) if out.exists() else {}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "WindowsPortal"}), timeout=10) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            return json.loads(out.read_text()) if out.exists() else {}
        data = None  # nothing known about it: cache that too
    except (OSError, ValueError):  # offline or garbled: a stale answer beats none
        return json.loads(out.read_text()) if out.exists() else {}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data))
    return data


def compat(appid, cached_only=False):
    """Highball's entry for a Steam app id: {"game": {...}} curated, {"prediction": {...}} odds, or {} if unknown."""
    return compat_fetch(COMPAT_URL.format(int(appid)), f"{int(appid)}.json", cached_only=cached_only) or {}


def compat_verdict(d):
    """One line for the library, e.g. 'Community reports say it runs · best on DXVK'; None if unknown."""
    if g := d.get("game"):
        line = COMPAT_STATUS.get(g.get("status"), g.get("status") or "Unknown")
        return line + (f" · best on {RENDERERS.get(g['renderer'], g['renderer'])}" if g.get("renderer") else "")
    if d.get("prediction"):
        return f"{d.get('label', d['prediction'].get('macPrediction'))} (prediction from Linux reports, ODbL)"
    return None


def compat_blocked(d):
    return (d.get("game") or {}).get("status", "").startswith("blocked")


def compat_report(game):
    """Text report for `compat`: a Steam app id, or a title looked up in installed Steam games, then the database."""
    if not str(game).isdigit():
        q = game.lower()
        installed = {t: a for b in bottles() if (bottle(b) / "drive_c/Program Files (x86)/Steam/steamapps").is_dir()
                     for a, t, *_ in steam_games(b)}
        index = (compat_fetch(COMPAT_INDEX, "games.json", max_age=86400) or {}).get("games", [])
        hits = [(t, a) for t, a in installed.items() if q in t.lower()] + \
               [(g["title"], g["steam_appid"]) for g in index if q in g["title"].lower() and g.get("steam_appid")]
        if not hits:
            return f"{game!r} isn't in Highball's database. Try its Steam app id (the number in its store URL)."
        exact = [h for h in hits if h[0].lower() == q]
        if len({a for _, a in hits}) > 1 and not exact:
            return "Which one?\n" + "\n".join(f"  {a}\t{t}" for t, a in dict.fromkeys(hits))
        game = (exact or hits)[0][1]
    d = compat(game)
    if not d:
        return f"No data for Steam app {game} (or offline). Browse https://gethighball.com/database/"
    g = d.get("game") or d.get("prediction", {})
    lines = [f"{g.get('title', game)} (Steam {game}): {compat_verdict(d)}"]
    if d.get("game"):
        lines += [f"  {g['notes']}"] if g.get("notes") else []
        lines += [f"  Known issue: {i['symptom']}\n    Fix: {i['fix']}" for i in g.get("knownIssues") or []]
        if g.get("anticheat"):
            lines.append(f"  Anti-cheat: {', '.join(g['anticheat'].get('names', []))}")
    else:
        lines.append(f"  {d.get('note', '')} ProtonDB tier: {g.get('protonTier')}.")
    lines.append(f"  {d.get('url', 'https://gethighball.com/database/')}  (data: {d.get('license')}, highball-db)")
    return "\n".join(lines)


def steam_appid_of(name, title):
    """Steam app id of a library entry steam_sync placed, else None."""
    f = DATA / "steam_sync.json"
    synced = json.loads(f.read_text()) if f.exists() else {}
    return next((a for a, e in synced.items() if e["title"] == title and e.get("bottle", STEAM_BOTTLE) == name), None)

# ---------- game stores: everything you own on Steam, Epic, GOG and itch.io, installed or not ----------
STORES = {"steam": "Steam", "epic": "Epic Games", "gog": "GOG", "itch": "itch.io", "amazon": "Amazon Games"}
STORE_DIR = DATA / "stores"  # tokens and cached library lists; readable by this user only
LEGENDARY_HOME = DATA / "legendary"
# GOG Galaxy's own public client credentials, which every third-party GOG client (Heroic, lgogdownloader, minigalaxy) uses.
GOG_CLIENT = ("46899977096215655", "9d85c43b1482497dbbce61f6e4aa173a433796eeae2ca8c5f6129f2dc4de46d9")
GOG_REDIRECT = "https://embed.gog.com/on_login_success?origin=client"
STORE_LOGIN = {
    "epic": ("https://legendary.gl/epiclogin", "Sign in to Epic, then copy the authorizationCode value shown (without quotes)."),
    "gog": ("https://auth.gog.com/auth?" + urllib.parse.urlencode({"client_id": GOG_CLIENT[0], "redirect_uri": GOG_REDIRECT,
                                                                   "response_type": "code", "layout": "client2"}),
            "Sign in to GOG. You land on a blank page: copy its whole address."),
    "itch": ("https://itch.io/user/settings/api-keys", "Click \"Generate new API key\" and copy the key."),
    "amazon": (None, "Sign in to Amazon. You land on amazon.com: copy that page's whole address."),  # Nile makes the URL
}


def store_file(file, data=None):
    f = STORE_DIR / file
    if data is None:
        return json.loads(f.read_text()) if f.exists() else {}
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    f.touch(0o600)
    f.write_text(json.dumps(data, indent=1))
    return data


def http_json(url, headers=None, data=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "WindowsPortal", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_authed(url, auth, folder, name=None):
    """Downloads url to folder (the file's own name unless given), sending auth only to url itself, never the CDN
    it redirects to. Kept in the cache, so a repeated install doesn't download again."""
    req = urllib.request.Request(url, headers={"User-Agent": "WindowsPortal"})
    for k, v in auth.items():
        req.add_unredirected_header(k, v)
    with urllib.request.urlopen(req) as r:
        dest = Path(folder) / (name or urllib.parse.unquote(Path(urllib.parse.urlparse(r.url).path).name))
        size = int(r.headers.get("Content-Length") or -1)
        if not (dest.exists() and dest.stat().st_size == size):
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest.with_suffix(dest.suffix + ".part"), "wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
            dest.with_suffix(dest.suffix + ".part").rename(dest)
    return dest


def store_connected(store):
    return {"steam": lambda: True, "epic": lambda: (LEGENDARY_HOME / "user.json").exists(),
            "gog": lambda: bool(store_file("gog.json")), "itch": lambda: bool(store_file("itch.json")),
            "amazon": lambda: (NILE_HOME / "current_user.json").exists()}[store]()


def store_login_start(store):
    """Opens the store's sign-in page; returns what to paste back."""
    if store not in STORE_LOGIN:
        sys.exit("store login: epic, gog, itch or amazon (Steam needs no login here: sign in to Steam in a bottle)")
    url = STORE_LOGIN[store][0]
    if store == "amazon":  # Nile makes a one-time device login; keep its half until the address comes back
        url = store_file("amazon-pending.json", nile_json("auth", "--login", "--non-interactive"))["url"]
    subprocess.run(["open", url])
    return STORE_LOGIN[store][1]


def store_login(store, code=None):
    """Connects an account. Without code, opens the sign-in page and says what to paste back."""
    if not code:
        return f"{store_login_start(store)}\nThen run: python3 portal.py store login {store} PASTED"
    code = code.strip().strip('"')
    if store == "amazon":
        q = urllib.parse.parse_qs(urllib.parse.urlparse(code).query)
        pending = store_file("amazon-pending.json") or sys.exit("start again: python3 portal.py store login amazon")
        nile("register", "--code", q.get("openid.oa2.authorization_code", [code])[0], "--client-id", pending["client_id"],
             "--code-verifier", pending["code_verifier"], "--serial", pending["serial"])
        (STORE_DIR / "amazon-pending.json").unlink(missing_ok=True)
    elif store == "epic":
        legendary("auth", "--disable-webview", "--code", code)
    elif store == "gog":
        code = urllib.parse.parse_qs(urllib.parse.urlparse(code).query).get("code", [code])[0]  # the address or the code
        gog_token(grant_type="authorization_code", code=code, redirect_uri=GOG_REDIRECT)
    else:
        try:
            http_json("https://api.itch.io/profile", {"Authorization": f"Bearer {code}"})
        except urllib.error.HTTPError:
            sys.exit("itch.io didn't accept that API key")
        store_file("itch.json", {"key": code})
    store_list(store)
    return f"connected {STORES[store]}"


def store_logout(store):
    if store == "epic" and store_connected("epic"):
        legendary("auth", "--delete")
    if store == "amazon" and store_connected("amazon"):
        nile("auth", "--logout")
    for f in (f"{store}.json", f"{store}-library.json"):
        (STORE_DIR / f).unlink(missing_ok=True)


def store_list(store, refresh=True):
    """{id: {"title", "installed": bottle or None, ...}} of everything the account owns; cached for offline use."""
    if store == "steam":  # read from disk, so always fresh
        games = {}
        for b in bottles():
            installed = {a for a, *_ in steam_games(b)} if (steam_root(b) / "steamapps").is_dir() else set()
            for appid, title in steam_owned(b).items():
                if appid not in games or appid in installed:  # owned in several bottles: the one it's installed in
                    games[appid] = {"title": title, "bottle": b, "installed": b if appid in installed else None}
        return games
    if not refresh or not store_connected(store):
        return store_file(f"{store}-library.json")
    games = {"epic": epic_list, "gog": gog_list, "itch": itch_list, "amazon": amazon_list}[store]()
    records = store_file("installed.json")
    for gid, g in games.items():
        r = records.get(f"{store}:{gid}")
        g.setdefault("installed", r["bottle"] if r and (HOME / r["bottle"]).is_dir() else None)
    return store_file(f"{store}-library.json", games)


def store_install(store, gid, name):
    bottle(name)
    gid = str(gid)
    if store == "steam":  # Steam itself downloads it, in its window
        if not (steam := steam_exe(name, "steam.exe")):
            sys.exit(f"Steam isn't installed in {name}")
        return run(name, str(steam), f"steam://install/{gid}", wait=False)
    before = programs(name)
    title = (store_list(store, refresh=False).get(gid) or {}).get("title")
    path = {"epic": epic_install, "gog": gog_install, "itch": itch_install, "amazon": amazon_install}[store](name, gid)
    added = register_new(name, before) if store in ("epic", "amazon") else install_file(name, str(path), title)
    target = next(iter(added.values()), None)
    store_file("installed.json", {**store_file("installed.json"),
                                  f"{store}:{gid}": {"bottle": name, "title": title, "target": target}})
    games = store_list(store, refresh=False)
    if gid in games:
        games[gid]["installed"] = name
        store_file(f"{store}-library.json", games)
    return added


def store_play(store, gid):
    gid = str(gid)
    g = store_list(store, refresh=False).get(gid) or {}
    if store == "steam":
        if not g.get("installed"):
            sys.exit("not installed; install it first")
        return run(g["installed"], str(steam_exe(g["installed"], "steam.exe")), "-applaunch", gid, wait=False)
    r = store_file("installed.json").get(f"{store}:{gid}") or sys.exit("not installed by Windows Portal; install it first")
    if store in ("epic", "amazon"):
        return (epic_launch if store == "epic" else amazon_launch)(r["bottle"], gid)
    if not r.get("target"):
        sys.exit(f"don't know which program starts it; use Add Program in bottle {r['bottle']}")
    return run(r["bottle"], r["target"], wait=False)


# Steam: the library the Windows Steam client already keeps on disk after one sign-in. No password or API key.
def steam_root(name):
    return bottle(name) / "drive_c/Program Files (x86)/Steam"


def steam_owned(name):
    """{appid: title} of games the account signed in to a bottle's Steam owns: appcache/librarycache has a folder
    (older clients: files) per owned app, and appinfo.vdf says which are games."""
    cache = steam_root(name) / "appcache/librarycache"
    ids = {int(m.group()) for p in cache.iterdir() if (m := re.match(r"\d+", p.name))} if cache.is_dir() else set()
    info = steam_appinfo(steam_root(name) / "appcache/appinfo.vdf", ids) if ids else {}
    return {str(a): t for a, (t, kind) in sorted(info.items(), key=lambda i: str(i[1][0]).lower()) if kind == "game" and t}


def steam_appinfo(path, wanted):
    """{appid: (name, type)} from Steam's binary appinfo.vdf (formats 28 and 29), for the appids in wanted."""
    try:
        b = Path(path).read_bytes()
    except OSError:
        return {}
    if len(b) < 16 or struct.unpack_from("<I", b, 0)[0] not in (0x07564428, 0x07564429):
        return {}
    try:
        return _appinfo(b, wanted)
    except (ValueError, IndexError, struct.error):
        return {}  # mid-write or a format Steam hasn't told anyone about: no library rather than a crash


def _appinfo(b, wanted):
    magic, = struct.unpack_from("<I", b, 0)
    strings, off = None, 8
    if magic == 0x07564429:  # keys are indexes into a string table at the end of the file
        table, = struct.unpack_from("<q", b, off)
        off += 8
        count, = struct.unpack_from("<I", b, table)
        strings, p = [], table + 4
        for _ in range(count):
            end = b.index(b"\0", p)
            strings.append(b[p:end].decode("utf-8", "replace"))
            p = end + 1

    def cstr(o):
        end = b.index(b"\0", o)
        return b[o:end].decode("utf-8", "replace"), end + 1

    def obj(o):  # binary KeyValues: type byte, key, value; 0x08 closes the object
        out = {}
        while (t := b[o]) != 8:
            o += 1
            if strings is None:
                key, o = cstr(o)
            else:
                key, o = strings[struct.unpack_from("<I", b, o)[0]], o + 4
            if t == 0:
                out[key.lower()], o = obj(o)
            elif t == 1:
                out[key.lower()], o = cstr(o)
            elif t in (2, 3, 4, 6):
                out[key.lower()], o = struct.unpack_from("<i", b, o)[0], o + 4
            elif t in (7, 10):
                out[key.lower()], o = struct.unpack_from("<q", b, o)[0], o + 8
            else:
                raise ValueError(f"value type {t}")
        return out, o + 1

    apps = {}
    while (appid := struct.unpack_from("<I", b, off)[0]):
        size, = struct.unpack_from("<I", b, off + 4)
        start, off = off + 8, off + 8 + size
        if appid in wanted:
            try:  # skip state, update time, token, hashes and change number (60 bytes) to the KeyValues
                root, _ = obj(start + 60)
                common = root.get("appinfo", root).get("common", {})
                apps[appid] = (common.get("name"), str(common.get("type", "")).lower())
            except (ValueError, IndexError, struct.error, AttributeError):
                pass  # one odd entry shouldn't hide the rest of the library
    return apps


# Epic: through Legendary (github.com/legendary-gl/legendary), which installs and launches Epic games without the Epic
# launcher, whose installs fail under Wine. Your login stays in LEGENDARY_HOME.
def legendary(*args, stream=False):
    exe = DATA / "tools/legendary"
    if not exe.exists():
        if platform.machine() != "arm64":  # the pinned build is Apple Silicon only
            exe = Path(shutil.which("legendary") or sys.exit("Epic needs Legendary on Intel Macs: pip3 install legendary-gl"))
        else:
            exe.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(fetch("legendary"), exe)
            exe.chmod(0o755)
    e = {**os.environ, "LEGENDARY_CONFIG_PATH": str(LEGENDARY_HOME)}
    if stream:  # installs: show progress
        if rc := subprocess.run([str(exe), *args], env=e).returncode:
            sys.exit(f"legendary {args[0]} failed ({rc})")
        return ""
    p = subprocess.run([str(exe), *args], env=e, capture_output=True, text=True)
    if p.returncode:
        sys.exit(f"legendary {args[0]} failed: {(p.stderr or p.stdout).strip().splitlines()[-1:] or p.returncode}")
    return p.stdout


def legendary_json(*args):
    out = legendary(*args)
    starts = [i for i in (out.find("["), out.find("{")) if i >= 0]
    return json.loads(out[min(starts):]) if starts else None


def epic_installed():
    """{app_name: (install folder, executable)} for games Legendary installed whose folder still exists."""
    return {g["app_name"]: (g["install_path"], g.get("executable", "")) for g in legendary_json("list-installed", "--json") or []
            if g.get("install_path") and os.path.isdir(g["install_path"])}


def epic_list():
    where = {app: next((b for b in bottles() if str(Path(path).resolve()).startswith(f"{(HOME / b / 'drive_c').resolve()}/")), None)
             for app, (path, _) in epic_installed().items()}
    return {g["app_name"]: {"title": g.get("app_title") or g["app_name"], "installed": where.get(g["app_name"])}
            for g in legendary_json("list", "--platform", "Windows", "--json") or []}


def epic_install(name, app):
    base = bottle(name) / "drive_c/Games"
    base.mkdir(parents=True, exist_ok=True)
    # -y answers the confirmations and --skip-sdl the optional-content prompt, which would otherwise wait on stdin
    legendary("install", app, "--platform", "Windows", "--base-path", str(base), "-y", "--skip-sdl", stream=True)
    path, exe = epic_installed().get(app) or sys.exit(f"Legendary didn't install {app}")
    title = (store_list("epic", refresh=False).get(app) or {}).get("title") or app
    target = str(Path(path) / exe.replace("\\", "/"))
    store_file("installed.json", {**store_file("installed.json"), f"epic:{app}": {"bottle": name, "title": title, "target": target}})
    add_program(name, target, title)
    return None


def launcher_app_of(name, target):
    """(store, id) if target is an Epic or Amazon game Windows Portal installed in this bottle: those start through
    their store's tool, for a login token (Epic) or the store's variables (Amazon)."""
    if not (STORE_DIR / "installed.json").exists():
        return None
    return next((tuple(k.split(":", 1)) for k, r in store_file("installed.json").items()
                 if k.split(":", 1)[0] in ("epic", "amazon") and r["bottle"] == name and r.get("target") == target), None)


def epic_launch(name, app, *extra):
    """Starts an Epic game with the one-time login token Legendary fetches; most Epic games refuse to start without it."""
    info = legendary_json("launch", app, "--json", "--skip-version-check", "--no-wine")  # --no-wine: we run Wine ourselves
    folder = Path(info["game_directory"])
    exe = folder / info["game_executable"].replace("\\", "/")
    args = [*info.get("egl_parameters", []), *info.get("game_parameters", []), *info.get("user_parameters", []), *extra]
    return subprocess.Popen([wine(name), str(exe), *args], env={**env(name, str(exe)), **(info.get("environment") or {})},
                            cwd=info.get("working_directory") or folder)


# GOG: your library and its offline installers, through GOG's own web API.
def gog_token(**params):
    t = http_json("https://auth.gog.com/token?" + urllib.parse.urlencode(
        {"client_id": GOG_CLIENT[0], "client_secret": GOG_CLIENT[1], **params}))
    t["expires_at"] = time.time() + t.get("expires_in", 3600) - 60
    return store_file("gog.json", t)


def gog_auth():
    t = store_file("gog.json") or sys.exit("connect GOG first: python3 portal.py store login gog")
    if time.time() > t["expires_at"]:
        t = gog_token(grant_type="refresh_token", refresh_token=t["refresh_token"])
    return {"Authorization": f"Bearer {t['access_token']}"}


def gog_list():
    games, page, pages = {}, 1, 1
    while page <= pages:
        d = http_json(f"https://embed.gog.com/account/getFilteredProducts?mediaType=1&page={page}", gog_auth())
        pages, page = d.get("totalPages", 1), page + 1
        for g in d.get("products", []):
            games[str(g["id"])] = {"title": g.get("title", g["id"]), "windows": (g.get("worksOn") or {}).get("Windows", True)}
    return games


def gog_install(name, gid):
    """Downloads a game's Windows installer (every part of it) and returns the .exe to run."""
    d = http_json(f"https://embed.gog.com/account/gameDetails/{gid}.json", gog_auth())
    langs = {lang: files for lang, files in d.get("downloads", [])}  # [["English", {"windows": [...], "mac": [...]}], ...]
    files = (langs.get("English") or next(iter(langs.values()), {})).get("windows")
    if not files:
        sys.exit("GOG has no Windows installer for this game")
    parts = [fetch_authed(f"https://embed.gog.com{f['manualUrl']}", gog_auth(), CACHE / "gog" / gid) for f in files]
    return next(p for p in parts if p.suffix.lower() == ".exe")  # setup_*.exe; its .bin parts sit beside it


# itch.io: owned and claimed games, with a personal API key.
def itch_auth():
    k = store_file("itch.json").get("key") or sys.exit("connect itch.io first: python3 portal.py store login itch")
    return {"Authorization": f"Bearer {k}"}


def itch_windows(o):  # the API has said "windows" three ways over the years
    return bool(o.get("p_windows") or "p_windows" in (o.get("traits") or []) or (o.get("platforms") or {}).get("windows"))


def itch_list():
    games = {}
    for page in range(1, 200):
        keys = http_json(f"https://api.itch.io/profile/owned-keys?page={page}", itch_auth()).get("owned_keys") or []
        if not keys:
            break
        for k in keys:
            g = k.get("game") or {}
            games[str(k["id"])] = {"title": g.get("title", "?"), "game_id": k.get("game_id", g.get("id")), "windows": itch_windows(g)}
    return games


def itch_install(name, kid):
    g = store_list("itch", refresh=False).get(kid) or sys.exit("unknown itch.io game; run: python3 portal.py store list itch")
    ups = http_json(f"https://api.itch.io/games/{g['game_id']}/uploads?download_key_id={kid}", itch_auth()).get("uploads", [])
    win = [u for u in ups if itch_windows(u) and not u.get("demo") and "demo" not in (u.get("traits") or [])]
    if not win:
        sys.exit("this game has no Windows download on itch.io")
    u = win[0]  # the developer's first Windows upload is the main one
    return fetch_authed(f"https://api.itch.io/uploads/{u['id']}/download?download_key_id={kid}", itch_auth(),
                        CACHE / "itch" / kid, u.get("filename"))


# Amazon Games (Prime Gaming): through Nile (github.com/imLinguin/nile), Heroic's Amazon client. Login stays in NILE_HOME.
NILE_HOME = DATA / "nile"


def nile(*args, stream=False):
    exe = DATA / "tools/nile"
    if not exe.exists():
        if platform.machine() != "arm64":
            exe = Path(shutil.which("nile") or sys.exit("Amazon Games needs Nile on Intel Macs: pip3 install git+https://github.com/imLinguin/nile"))
        else:
            exe.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(fetch("nile"), exe)
            exe.chmod(0o755)
    e = {**os.environ, "NILE_CONFIG_PATH": str(DATA)}  # Nile adds its own "nile" folder: NILE_HOME
    if stream:
        if rc := subprocess.run([str(exe), *args], env=e).returncode:
            sys.exit(f"nile {args[0]} failed ({rc})")
        return ""
    p = subprocess.run([str(exe), *args], env=e, capture_output=True, text=True)
    if p.returncode:
        sys.exit(f"nile {args[0]} failed: {(p.stderr or p.stdout).strip().splitlines()[-1:] or p.returncode}")
    return p.stdout


def nile_json(*args):
    out = nile(*args)
    starts = [i for i in (out.find("["), out.find("{")) if i >= 0]
    return json.loads(out[min(starts):]) if starts else None


def nile_file(name):
    f = NILE_HOME / f"{name}.json"
    return json.loads(f.read_text()) if f.exists() else []


def amazon_list():
    nile("library", "sync")
    installed = {g["id"]: g["path"] for g in nile_file("installed") if os.path.isdir(g.get("path", ""))}
    where = {gid: next((b for b in bottles() if str(Path(path).resolve()).startswith(f"{(HOME / b / 'drive_c').resolve()}/")), None)
             for gid, path in installed.items()}
    return {g["product"]["id"]: {"title": g["product"].get("title") or g["product"]["id"], "installed": where.get(g["product"]["id"])}
            for g in nile_file("library") if g.get("product", {}).get("id")}


def amazon_install(name, gid):
    base = bottle(name) / "drive_c/Games"
    base.mkdir(parents=True, exist_ok=True)
    nile("install", gid, "--base-path", str(base), stream=True)
    path = next((g["path"] for g in nile_file("installed") if g["id"] == gid), None) or sys.exit(f"Nile didn't install {gid}")
    fuel = json.loads((Path(path) / "fuel.json").read_text()) if (Path(path) / "fuel.json").exists() else {}
    cmd = (fuel.get("Main") or {}).get("Command")
    target = str(Path(path) / cmd.replace("\\", "/")) if cmd else str(main_exe(path) or "")
    if not target:
        sys.exit(f"no program found in {path}")
    title = (store_list("amazon", refresh=False).get(gid) or {}).get("title") or gid
    store_file("installed.json", {**store_file("installed.json"), f"amazon:{gid}": {"bottle": name, "title": title, "target": target}})
    add_program(name, target, title)


def amazon_launch(name, gid, *extra):
    """Starts an Amazon game with the variables its Fuel SDK expects (entitlement, SKU), as Nile works them out."""
    info = nile_json("launch", gid, "--json")  # --json: print the command instead of running it
    cmd = info["command"]["instruction"]
    return subprocess.Popen([wine(name), cmd, *info["command"].get("arguments", []), *extra],
                            env={**env(name, cmd), **(info.get("env") or {})}, cwd=info.get("game_directory") or Path(cmd).parent)


# Cover art: Steam's own for Steam games and any game the umu database matches to a Steam app id; SteamGridDB
# (free API key) for the rest.
UMU_STORES = {"epic": "egs", "gog": "gog", "amazon": "amazon", "itch": "itchio"}


def umu_appid(store, gid):
    """Steam app id of a game from another store, via the umu database (github.com/Open-Wine-Components/umu-database),
    which Heroic, Lutris and Bottles share. Its ids are umu-<Steam app id> for games that are also on Steam."""
    if store == "steam":
        return gid
    cache = CACHE / "umu.json"
    known = json.loads(cache.read_text()) if cache.exists() else {}
    key = f"{store}:{gid}"
    if key not in known:
        try:
            hits = http_json("https://umu.openwinecomponents.org/umu_api.php?" + urllib.parse.urlencode(
                {"store": UMU_STORES.get(store, store), "codename": gid}))
        except (OSError, ValueError):
            return None  # offline: ask again next time
        m = re.fullmatch(r"umu-(\d+)", (hits or [{}])[0].get("umu_id") or "")
        known[key] = m.group(1) if m else None
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(known))
    return known[key]


def art_key(key=None):
    if key:
        store_file("art.json", {"steamgriddb": key.strip()})
    return "set" if store_file("art.json").get("steamgriddb") else "not set (games not on Steam get a generic icon)"


def cover_art(store, gid, title, fetch=True):
    """Cached PNG cover (portrait, 128 px tall) for a store game, or None."""
    out = CACHE / "art" / f"{store}-{re.sub(r'[^A-Za-z0-9_.-]', '_', str(gid))}.png"
    miss = out.with_suffix(".none")
    if out.exists() or not fetch or (miss.exists() and time.time() - miss.stat().st_mtime < 7 * 86400):
        return out if out.exists() else None
    out.parent.mkdir(parents=True, exist_ok=True)
    src = None
    try:
        if appid := umu_appid(store, gid):
            src = f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/library_600x900.jpg"
        elif key := store_file("art.json").get("steamgriddb"):
            auth = {"Authorization": f"Bearer {key}"}
            found = http_json("https://www.steamgriddb.com/api/v2/search/autocomplete/" + urllib.parse.quote(title), auth).get("data")
            if found:
                grids = http_json(f"https://www.steamgriddb.com/api/v2/grids/game/{found[0]['id']}?dimensions=600x900", auth).get("data")
                src = grids[0]["url"] if grids else None
        if src:
            tmp = out.with_suffix(".jpg")
            with urllib.request.urlopen(urllib.request.Request(src, headers={"User-Agent": "WindowsPortal"}), timeout=30) as r:
                tmp.write_bytes(r.read())
            ok = subprocess.run(["sips", "-s", "format", "png", "--resampleHeight", "128", str(tmp), "--out", str(out)],
                                capture_output=True).returncode == 0
            tmp.unlink(missing_ok=True)
            if ok:
                return out
    except (OSError, ValueError, KeyError, IndexError):
        pass
    miss.touch()  # don't ask again for a week
    return None


def store_cli(cmd, *a):
    if cmd == "login":
        print(store_login(*a))
    elif cmd == "logout":
        store_logout(*a)
    elif cmd == "list":
        for gid, g in store_list(*a).items():
            print(f"{gid}\t{g['title']}" + (f"\t(installed in {g['installed']})" if g.get("installed") else ""))
    elif cmd == "install":
        print(store_install(*a))
    elif cmd == "play":
        p = store_play(*a)
        if hasattr(p, "wait"):
            p.wait()
    else:
        sys.exit(__doc__)


def mac_app(name, target, title=None):
    title = (title or Path(target).stem).replace("/", "-")
    app = APPS / f"{title}.app"
    owner = app / "Contents/MacOS/launch"
    if owner.exists() and f"WINEPREFIX={shlex.quote(str(bottle(name)))} " not in owner.read_text():
        app = APPS / f"{title} ({name}).app"  # same program in another bottle: don't clobber its app
    (app / "Contents/MacOS").mkdir(parents=True, exist_ok=True)
    exports = " ".join(f"{k}={shlex.quote(v)}" for k, v in wine_env(name, target).items())
    script = app / "Contents/MacOS/launch"
    launch, fix = shlex.quote(target), ""
    appid = steam_appid(name, target)
    if steam := steam_exe(name, "steam.exe" if appid else target):  # same as fix_steam() and run(), in shell so it repeats after Steam updates
        (DATA / "steamwebhelper.exe").write_bytes(WEBHELPER)
        w, d = shlex.quote(str(DATA / "steamwebhelper.exe")), shlex.quote(str(steam.parent / "bin/cef/cef.win64"))
        fix = f'cmp -s {w} {d}/steamwebhelper.exe || {{ mv -f {d}/steamwebhelper.exe {d}/steamwebhelper_real.exe && cp {w} {d}/steamwebhelper.exe; }}\n'
        launch = f"{shlex.quote(str(steam))} -noverifyfiles" + (f" -applaunch {appid}" if appid else "")
    if hit := launcher_app_of(name, target):  # via Legendary/Nile for the login token, so through this script
        script.write_text(f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(Path(__file__).resolve()))} "
                          f"store play {hit[0]} {shlex.quote(hit[1])}\n")
    else:
        script.write_text(f"#!/bin/sh\ncd {shlex.quote(str(Path(target).parent))}\n{fix}"
                          f"export {exports}\nexec {shlex.quote(wine(name))} start /unix {launch}\n")
    script.chmod(0o755)
    plist = {"CFBundleExecutable": "launch", "CFBundleName": title, "CFBundlePackageType": "APPL",
             "CFBundleIdentifier": f"local.windowsportal.{name}.{zlib.crc32(target.encode())}", "LSUIElement": True}
    (app / "Contents/Resources").mkdir(exist_ok=True)
    if app_icon(name, target, app / "Contents/Resources/icon.icns"):
        plist["CFBundleIconFile"] = "icon"
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps(plist))
    subprocess.run(["touch", str(app)])  # makes Finder drop its cached icon
    return app


def win_to_mac(name, winpath):
    """C:\\Program Files\\x.exe -> <bottle>/drive_c/Program Files/x.exe"""
    drive, _, rest = winpath.partition(":")
    return bottle(name) / "dosdevices" / f"{drive.lower()}:" / rest.lstrip("\\").replace("\\", "/")


def lnk_target(path):
    """The Windows path a .lnk points at, or None."""
    try:
        return _lnk(path)[0]
    except (OSError, ValueError, IndexError):
        return None


def lnk_icon(path):
    """(icon file, icon index) from a Windows .lnk, per [MS-SHLLINK]."""
    target, icon, index = _lnk(path)
    return (icon, index) if icon and "%" not in icon else (target, 0)


def _lnk(path):
    b = Path(path).read_bytes()
    u32 = lambda o: int.from_bytes(b[o:o + 4], "little")
    flags, index, off = u32(20), int.from_bytes(b[56:60], "little", signed=True), 76
    target = None
    if flags & 1:  # LinkTargetIDList
        off += 2 + int.from_bytes(b[off:off + 2], "little")
    if flags & 2:  # LinkInfo: LocalBasePath is a NUL-terminated ANSI string
        base = off + u32(off + 16)
        target = b[base:b.index(b"\0", base)].decode("latin-1") or None
        off += u32(off)
    strings, wide = [], flags & 0x80
    for bit in (4, 8, 0x10, 0x20, 0x40):  # name, relative path, working dir, args, icon location
        if flags & bit:
            n = int.from_bytes(b[off:off + 2], "little") * (2 if wide else 1)
            strings.append((bit, b[off + 2:off + 2 + n].decode("utf-16-le" if wide else "latin-1")))
            off += 2 + n
    return target, dict(strings).get(0x40), index


def pe_icon(path, index=0):
    """Largest image of an .exe/.dll's icon group as PNG or single-image ICO bytes."""
    import mmap
    with open(path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:  # big game exes never load fully
        u16 = lambda o: int.from_bytes(m[o:o + 2], "little")
        u32 = lambda o: int.from_bytes(m[o:o + 4], "little")
        pe = u32(0x3C)
        opt, nsec = pe + 24, u16(pe + 6)
        rsrc_rva = u32(opt + (112 if u16(opt) == 0x20B else 96) + 16)
        secs = [(u32(s + 12), u32(s + 8), u32(s + 20)) for s in range(opt + u16(pe + 20), opt + u16(pe + 20) + 40 * nsec, 40)]
        at = lambda rva: next(raw + rva - va for va, size, raw in secs if va <= rva < va + size)
        root = at(rsrc_rva)

        def entries(d):
            return [(u32(e), u32(e + 4)) for e in range(root + d + 16, root + d + 16 + 8 * (u16(root + d + 12) + u16(root + d + 14)), 8)]

        def resources(rtype):  # [(id, bytes)] taking the first language of each
            out = []
            for tid, toff in entries(0):
                if tid == rtype:
                    for rid, roff in entries(toff & 0x7FFFFFFF):
                        leaf = root + (entries(roff & 0x7FFFFFFF)[0][1])
                        out.append((rid, m[at(u32(leaf)):at(u32(leaf)) + u32(leaf + 4)]))
            return out

        groups, images = resources(14), dict(resources(3))
        grp = dict(groups).get(-index) if index < 0 else groups[index][1] if index < len(groups) else None
        if not grp:
            return None
        best = max((grp[6 + 14 * i:20 + 14 * i] for i in range(int.from_bytes(grp[4:6], "little"))),
                   key=lambda e: ((e[0] or 256), int.from_bytes(e[6:8], "little")))
        data = images[int.from_bytes(best[12:14], "little")]
    if data[:4] == b"\x89PNG":
        return data
    return b"\0\0\1\0\1\0" + best[:12] + (22).to_bytes(4, "little") + data


def icon_png(name, target, size=256):
    """Cached PNG of a .lnk/.exe/.ico's icon, or None if there's nothing usable."""
    out = CACHE / "icons" / f"{zlib.crc32(f'{name}|{target}'.encode())}-{size}.png"
    if out.exists():
        return out
    try:
        src, index = lnk_icon(target) if target.lower().endswith(".lnk") else (target, 0)
        if src and ":" in src[:3]:
            src = str(win_to_mac(name, src))
        if not src or not os.path.exists(src):
            return None
        img = Path(src).read_bytes() if src.lower().endswith(".ico") else pe_icon(src, index)
        if not img:
            return None
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".src")
        tmp.write_bytes(img)
        ok = subprocess.run(["sips", "-s", "format", "png", "-z", str(size), str(size), str(tmp), "--out", str(out)],
                            capture_output=True).returncode == 0
        tmp.unlink()
        return out if ok else None
    except (OSError, ValueError, IndexError, StopIteration, KeyError):
        return None  # malformed or unusual file: generic icon rather than failing


def app_icon(name, target, dest):
    """Writes dest .icns; False means keep the generic icon."""
    png = icon_png(name, target)
    return bool(png) and subprocess.run(["sips", "-s", "format", "icns", str(png), "--out", str(dest)],
                                        capture_output=True).returncode == 0


def delete(name):
    kill(name)
    prefix = f"WINEPREFIX={shlex.quote(str(bottle(name)))} "
    for s in APPS.glob("*.app/Contents/MacOS/launch"):
        if prefix in s.read_text():
            shutil.rmtree(s.parents[2])
    shutil.rmtree(bottle(name))
    lib = library()
    if lib.pop(name, None) is not None:
        save_library(lib)


def export(name, dest):
    kill(name)  # flushes the registry to disk
    print(shutil.make_archive(dest, "gztar", HOME, name))


def import_(archive):
    with tarfile.open(archive) as t:
        tops = {m.name.split("/")[0] for m in t.getmembers()}
        if len(tops) != 1:
            sys.exit("not a Windows Portal bottle archive")
        bottle(name := tops.pop(), exists=False)
        if (HOME / name).exists():
            sys.exit(f"bottle {name} already exists")
        HOME.mkdir(parents=True, exist_ok=True)
        t.extractall(HOME, filter="tar")  # rejects absolute and ../ paths
    print(name)


def package(dest=Path.home() / "Applications"):
    """Builds Windows Portal.app around this script and the Python running it."""
    app = Path(dest) / "Windows Portal.app"
    shutil.rmtree(app, ignore_errors=True)
    (app / "Contents/MacOS").mkdir(parents=True)
    (app / "Contents/Resources").mkdir()
    shutil.copy(__file__, app / "Contents/Resources/portal.py")
    shutil.copy(Path(__file__).with_name("icon.png"), app / "Contents/Resources/icon.png")  # library's fallback icon
    subprocess.run(["sips", "-s", "format", "icns", "-z", "512", "512", str(Path(__file__).with_name("icon.png")),
                    "--out", str(app / "Contents/Resources/icon.icns")], check=True, capture_output=True)
    # ponytail: pins this machine's Python (needs 3.11.4+ with Tk); bundle Python with PyInstaller to share the app.
    # Finder-launched apps get a bare PATH, so add Homebrew's for wine64/winetricks/brew.
    launch = app / "Contents/MacOS/launch"
    # Run Python through a link inside the bundle: macOS then registers the process as this app, not as
    # a bare python3, which is what gives Tk proper activation, focus and first-click handling.
    os.symlink(sys.executable, app / "Contents/MacOS/python")  # not realpath: python3 keeps working across 3.x upgrades
    launch.write_text(f'#!/bin/sh\nexport PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"\n'
                      f'exec "$(dirname "$0")/python" "$(dirname "$0")/../Resources/portal.py" gui\n')
    launch.chmod(0o755)
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps({
        "CFBundleExecutable": "launch", "CFBundleName": "Windows Portal", "CFBundleDisplayName": "Windows Portal",
        "CFBundleIdentifier": "local.windowsportal", "CFBundlePackageType": "APPL", "CFBundleIconFile": "icon",
        "CFBundleShortVersionString": "1.0", "NSHighResolutionCapable": True}))
    print(app)


def drive_c(name):
    subprocess.run(["open", bottle(name) / "drive_c"])


def gui():
    import queue, threading, tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog

    BG, SIDE, CARD, HOVER, SEL, FG, DIM, ACCENT = ("#18181c", "#111114", "#222228", "#2e2e37", "#3b3170",
                                                   "#ececf0", "#8e8e98", "#7a5cff")
    root = tk.Tk()
    root.title("Windows Portal")
    root.geometry("1120x720")
    root.minsize(640, 420)
    root.configure(bg=BG)
    status = tk.StringVar()
    jobs = queue.Queue()  # worker threads never touch Tk; they post callables here
    state = {"filter": None, "selected": None, "items": [], "tiles": [], "manager": None,
             "stores": {}, "store_fetched": set(), "art_asked": set()}  # filter ("store", key) shows that store's library
    images = {}  # Tk forgets images Python garbage-collects, so keep refs

    def ui(fn, *a):
        jobs.put(lambda: fn(*a))

    def poll():
        while not jobs.empty():
            jobs.get()()
        root.after(100, poll)

    def bg(msg, fn, *a):
        status.set(msg)

        def work():
            try:
                fn(*a)
                ui(finished, None)
            except (SystemExit, Exception) as e:
                ui(finished, str(e))
        threading.Thread(target=work, daemon=True).start()

    def finished(err):
        status.set("")
        if err:
            messagebox.showerror("Windows Portal", err)
        refresh()

    def guarded(fn):
        def f(*_):
            try:
                fn()
            except SystemExit as e:
                messagebox.showerror("Windows Portal", str(e))
        return f

    def button(parent, text, fn, accent=False, color=None):
        # Labels, not Buttons: macOS Aqua buttons ignore colors.
        c = color or (ACCENT if accent else HOVER)
        b = tk.Label(parent, text=text, bg=c, fg="white", padx=16, pady=7,
                     font=("Helvetica", 13, "bold" if accent else "normal"))
        b.bind("<Button-1>", guarded(fn))
        return b

    def photo(path):
        if path not in images:
            images[path] = tk.PhotoImage(file=path)
        return images[path]

    def pick_bottle():
        bs = bottles()
        if isinstance(state["filter"], str):  # a bottle is selected in the sidebar (not a store)
            return state["filter"]
        if not bs:
            messagebox.showinfo("Windows Portal", "Create a bottle first (Manage Bottles → New Bottle).")
            return None
        if len(bs) == 1:
            return bs[0]
        n = simpledialog.askstring("Which bottle?", "Bottles: " + ", ".join(bs), initialvalue=bs[0])
        return n if n in bs else None

    # ---------- layout ----------
    side = tk.Frame(root, bg=SIDE, width=220)
    side.pack(side="left", fill="y")
    side.pack_propagate(False)
    tk.Label(side, text="Windows Portal", bg=SIDE, fg=FG, font=("Helvetica", 18, "bold")).pack(anchor="w", padx=18, pady=(20, 16))
    nav = tk.Frame(side, bg=SIDE)
    nav.pack(fill="x")
    acts = tk.Frame(side, bg=SIDE)
    acts.pack(side="bottom", fill="x", padx=14, pady=14)
    tk.Label(side, textvariable=status, bg=SIDE, fg=DIM, wraplength=190, justify="left").pack(side="bottom", anchor="w", padx=18)

    main = tk.Frame(root, bg=BG)
    main.pack(side="left", fill="both", expand=True)
    top = tk.Frame(main, bg=BG)
    top.pack(fill="x", padx=24, pady=(20, 10))
    heading = tk.Label(top, bg=BG, fg=FG, font=("Helvetica", 24, "bold"))
    heading.pack(side="left")
    query = tk.StringVar()
    tk.Entry(top, textvariable=query, bg=CARD, fg=FG, insertbackground=FG, relief="flat", width=26,
             highlightthickness=1, highlightbackground=HOVER, highlightcolor=ACCENT).pack(side="right", ipady=5)
    tk.Label(top, text="Search", bg=BG, fg=DIM).pack(side="right", padx=8)
    detail = tk.Frame(main, bg=SIDE, height=120)
    detail.pack(side="bottom", fill="x")
    detail.pack_propagate(False)
    canvas = tk.Canvas(main, bg=BG, highlightthickness=0)
    canvas.pack(fill="both", expand=True, padx=(16, 8))
    grid = tk.Frame(canvas, bg=BG)
    canvas.create_window(0, 0, window=grid, anchor="nw")
    grid.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: layout())
    def inside(w, parent):  # is widget w parent itself or one of its descendants?
        return w is not None and (str(w) == str(parent) or str(w).startswith(f"{parent}."))

    def wheel(e):
        under = root.winfo_containing(e.x_root, e.y_root)
        if inside(under, canvas):  # only scroll the grid, never dialogs or the sidebar
            canvas.yview_scroll(-e.delta, "units")
    canvas.bind_all("<MouseWheel>", wheel)
    query.trace_add("write", lambda *_: draw())

    # ---------- library ----------
    def refresh():
        draw_nav()
        if state["manager"]:
            state["manager"]()
        status.set("Loading library…")

        def work():  # Steam sync and icon extraction can take a moment, keep them off the UI thread
            try:
                if sync_steam():
                    ui(draw_nav)  # the Steam games bottle may be new
            except (SystemExit, Exception) as e:
                ui(status.set, f"Steam games: {e}")
            items = [(t, b, p, icon_png(b, p, 128)) for b in bottles() for t, p in programs(b).items()]
            ui(loaded, items)
        threading.Thread(target=work, daemon=True).start()

    def loaded(items):
        state["items"] = items
        if status.get().startswith("Loading"):  # keep a Steam sync error visible
            status.set("")
        draw()

    def draw_nav():
        for w in nav.winfo_children():
            w.destroy()
        rows = [(None, "All Programs")] + ([("", "BOTTLES")] if bottles() else []) + [(b, b) for b in bottles()] + \
               [("", "STORES")] + [(("store", k), v) for k, v in STORES.items()]
        for key, text in rows:
            if key == "":
                tk.Label(nav, text=text, bg=SIDE, fg=DIM, font=("Helvetica", 10, "bold")).pack(anchor="w", padx=18, pady=(14, 4))
                continue
            on = key == state["filter"]
            l = tk.Label(nav, text=text, anchor="w", bg=HOVER if on else SIDE, fg=FG if on else DIM,
                         padx=18, pady=7, font=("Helvetica", 13))
            l.pack(fill="x")
            l.bind("<Button-1>", lambda e, k=key: (state.update(filter=k, selected=None), draw_nav(), draw()))

    def store_view():
        f = state["filter"]
        return f[1] if isinstance(f, tuple) else None

    def store_items(store):
        """Tiles for a store's library: (title, status, ("store", store, id, info), icon)."""
        if store not in state["store_fetched"]:  # cached list now, the store's current one when it arrives
            state["store_fetched"].add(store)
            state["stores"][store] = store_list(store, refresh=False)

            def work():
                try:
                    games = store_list(store)
                    ui(lambda: (state["stores"].__setitem__(store, games), store_view() == store and draw()))
                except (SystemExit, Exception) as e:
                    ui(status.set, f"{STORES[store]}: {e}")
            threading.Thread(target=work, daemon=True).start()
        games = state["stores"].get(store) or {}
        ordered = sorted(games.items(), key=lambda i: (not i[1].get("installed"), str(i[1]["title"]).lower()))
        arts = {gid: cover_art(store, gid, g["title"], fetch=False) for gid, g in ordered}
        missing = [(gid, g["title"]) for gid, g in ordered if not arts[gid] and (store, gid) not in state["art_asked"]]
        if missing:  # one worker fetches covers in order and redraws now and then, so the grid fills in as they arrive
            state["art_asked"].update((store, gid) for gid, _ in missing)

            def fetch_art():
                for i, (gid, title) in enumerate(missing, 1):
                    got = cover_art(store, gid, title)
                    if got and (i % 8 == 0 or i == len(missing)):
                        ui(lambda: store_view() == store and draw())
            threading.Thread(target=fetch_art, daemon=True).start()
        return [(g["title"], f"Installed in {g['installed']}" if g.get("installed") else
                 ("Not installed" if g.get("windows", True) else "No Windows version"), ("store", store, gid, g), arts[gid])
                for gid, g in ordered]

    def draw():
        for f, *_ in state["tiles"]:
            f.destroy()
        q = query.get().lower()
        store = store_view()
        if store:
            shown = [i for i in store_items(store) if q in str(i[0]).lower()]
            heading.config(text=STORES[store])
        else:
            shown = [i for i in state["items"] if state["filter"] in (None, i[1]) and q in i[0].lower()]
            heading.config(text=state["filter"] or "All Programs")
        state["tiles"] = [tile(i) for i in shown]
        if not shown:
            text = ("No programs here yet.\nUse Install Software or Add Program on the left." if not store else
                    "Install Steam in a bottle and sign in once:\nevery game you own shows up here." if store == "steam" else
                    f"Connect your {STORES[store]} account below." if not store_connected(store) else "Loading your library…")
            f = tk.Label(grid, bg=BG, fg=DIM, font=("Helvetica", 14), pady=40, text=text)
            state["tiles"] = [(f, None, lambda c: None)]
        layout()
        show_detail()

    def tile(item):
        title, b, target, icon = item
        f = tk.Frame(grid, bg=CARD, width=172, height=206)
        f.pack_propagate(False)
        fallback = Path(__file__).with_name("icon.png")
        img = icon or (fallback if fallback.exists() else None)
        if img:
            pi = photo(str(img))
            if pi.width() > 128:  # the 1024px app icon
                pi = images.setdefault(f"{img}-small", pi.subsample(pi.width() // 128))
            tk.Label(f, image=pi, bg=CARD).pack(pady=(20, 10))
        tk.Label(f, text=title, bg=CARD, fg=FG, wraplength=150, font=("Helvetica", 12, "bold")).pack()
        tk.Label(f, text=b, bg=CARD, fg=DIM, font=("Helvetica", 10)).pack()

        def paint(c):
            for w in (f, *f.winfo_children()):
                w.config(bg=c)
        picked = lambda: state["selected"] == item
        for w in (f, *f.winfo_children()):
            w.bind("<Button-1>", lambda e: select(item))
            w.bind("<Double-Button-1>", lambda e: play(item))
        def leave(e):  # moving onto the tile's own labels also fires <Leave>; only un-hover when truly outside
            under = f.winfo_containing(e.x_root, e.y_root)
            if not inside(under, f):
                paint(SEL if picked() else CARD)
        f.bind("<Enter>", lambda e: picked() or paint(HOVER))
        f.bind("<Leave>", leave)
        paint(SEL if picked() else CARD)
        return f, item, paint

    def layout():
        cols = max(1, canvas.winfo_width() // 188)
        for i, (f, *_) in enumerate(state["tiles"]):
            f.grid(row=i // cols, column=i % cols, padx=8, pady=8)

    def select(item):
        state["selected"] = item
        for f, it, paint in state["tiles"]:
            paint(SEL if it == item else CARD)
        show_detail()

    def play(item):
        title, b, target, _ = item
        if isinstance(target, tuple):  # a store game
            _, store, gid, g = target
            if not g.get("installed"):
                return install_store_game(item)
            bg(f"Starting {title}…", store_play, store, gid)
            return
        appid = steam_appid_of(b, title)
        if appid and compat_blocked(compat(appid, cached_only=True)) and not messagebox.askyesno(
                "Windows Portal", f"Highball's database says {title} won't run under Wine on a Mac: "
                f"{compat_verdict(compat(appid, cached_only=True))}.\n\nLaunch anyway?"):
            return
        run(b, target, wait=False)
        status.set(f"Launched {title}")
        root.after(4000, lambda: status.get() == f"Launched {title}" and status.set(""))

    def install_store_game(item):
        title, _, (_, store, gid, g), _ = item
        if store == "steam":  # Steam downloads it in the bottle it's owned in
            bg(f"Opening Steam to install {title}…", store_install, store, gid, g["bottle"])
            return
        n = pick_bottle()
        if n:
            bg(f"Installing {title} into {n}… (large games take a while)", store_install, store, gid, n)

    def connect_store(store):
        try:
            how = store_login_start(store)  # opens the sign-in page
        except SystemExit as e:
            return messagebox.showerror("Windows Portal", str(e))
        code = simpledialog.askstring(f"Connect {STORES[store]}", f"{how}\n\nPaste it here:")
        if code:
            state["store_fetched"].discard(store)
            bg(f"Connecting {STORES[store]}…", store_login, store, code)

    def store_detail(store):
        bar = tk.Frame(detail, bg=SIDE)
        bar.pack(side="right", padx=24)
        if store == "steam":
            tk.Label(detail, text="Your Steam library comes from the Steam you're signed in to in a bottle.",
                     bg=SIDE, fg=DIM, font=("Helvetica", 13)).pack(side="left", padx=24)
        elif not store_connected(store):
            tk.Label(detail, text=f"Not connected. Sign in once; Windows Portal keeps the login on this Mac.",
                     bg=SIDE, fg=DIM, font=("Helvetica", 13)).pack(side="left", padx=24)
            button(bar, f"Connect {STORES[store]}…", lambda: connect_store(store), True).pack(side="left", padx=4)
            return
        else:
            tk.Label(detail, text="Select a game. Double-click to install or play.",
                     bg=SIDE, fg=DIM, font=("Helvetica", 13)).pack(side="left", padx=24)
            button(bar, "Disconnect", lambda: messagebox.askyesno("Windows Portal", f"Disconnect {STORES[store]}?")
                   and (store_logout(store), state["stores"].pop(store, None), draw())).pack(side="left", padx=4)
        button(bar, "Refresh", lambda: (state["store_fetched"].discard(store), draw())).pack(side="left", padx=4)
        if store != "steam":
            button(bar, "Cover Art…", set_art_key).pack(side="left", padx=4)

    def set_art_key():
        k = simpledialog.askstring("Cover art", "Games also on Steam get Steam's covers. For the rest, paste a free "
                                   f"SteamGridDB API key (steamgriddb.com → Preferences → API).\n\nNow: {art_key()}")
        if k:
            art_key(k)
            for f in (CACHE / "art").glob("*.none"):  # ask again for the ones that had none
                f.unlink()
            state["art_asked"].clear()
            draw()

    def verdict_label(parent, appid, b=None):
        """Highball's verdict for a Steam app id, fetched off the UI thread; click opens its page."""
        verdict = tk.Label(parent, text="Checking compatibility…", bg=SIDE, fg=DIM, cursor="hand2")
        verdict.pack(anchor="w")

        def shown(d):
            if verdict.winfo_exists():
                best = (d.get("game") or {}).get("renderer")
                hint = (f" (Graphics… to switch)" if b and best in GRAPHICS[engine(b)] and best != graphics(b) else
                        " (not on the native engine)" if b and engine(b) == "arm64" and best in ("d3dmetal", "dxmt") else "")
                verdict.config(text=f"{compat_verdict(d) or 'Not in the compatibility database'}{hint}  ↗",
                               fg="#ff6b6b" if compat_blocked(d) else DIM)
                verdict.bind("<Button-1>", lambda e: subprocess.run(["open", d.get("url", "https://gethighball.com/database/")]))
        threading.Thread(target=lambda: ui(shown, compat(appid)), daemon=True).start()

    def game_settings_dialog(b, target, title):
        now = set_game(b, target)
        opts = GRAPHICS[engine(b)]
        g = simpledialog.askstring(f"{title}: graphics", f"Graphics for this game only (bottle: {graphics(b)}).\n"
                                   f"{', '.join(opts)}, or default for the bottle's.", initialvalue=now.get("graphics", "default"))
        if g is None:
            return
        if g == "d3dmetal" and engine(b) == "wine10" and not d3dmetal_accepted():
            if not messagebox.askyesno("D3DMetal license", D3DMETAL_LICENSE + "\n\nAccept?"):
                return
            accept_d3dmetal(ask=False)
        m = simpledialog.askstring(f"{title}: mouse", "Mouse: default, or force for games whose camera spins or that "
                                   "lose the pointer (enable, disable also work).", initialvalue=now.get("mouse", "default"))
        if m is None:
            return

        def apply():
            set_game(b, target, "graphics", g.strip())
            set_game(b, target, "mouse", m.strip())
        bg(f"Saving settings for {title}…", apply)

    def show_detail():
        for w in detail.winfo_children():
            w.destroy()
        shown = [t[1] for t in state["tiles"]]
        item = state["selected"] if state["selected"] in shown else None
        if not item and store_view():
            return store_detail(store_view())
        if not item:
            tk.Label(detail, text="Select a program to see its options. Double-click to play.",
                     bg=SIDE, fg=DIM, font=("Helvetica", 13)).pack(padx=24, pady=44, anchor="w")
            return
        title, b, target, _ = item
        info = tk.Frame(detail, bg=SIDE)
        info.pack(side="left", padx=24)
        tk.Label(info, text=title, bg=SIDE, fg=FG, font=("Helvetica", 20, "bold")).pack(anchor="w")
        if isinstance(target, tuple):  # a store game
            _, store, gid, g = target
            tk.Label(info, text=f"{STORES[store]}  ·  {b}", bg=SIDE, fg=DIM).pack(anchor="w")
            bar = tk.Frame(detail, bg=SIDE)
            bar.pack(side="right", padx=24)
            if g.get("installed"):
                button(bar, "▶  Play", lambda: play(item), True).pack(side="left", padx=4)
            elif g.get("windows", True):
                button(bar, "Install…" if store != "steam" else "Install in Steam", lambda: install_store_game(item), True).pack(side="left", padx=4)

            def find_appid():  # umu matches other stores' games to Steam's, which Highball's database is keyed on
                appid = umu_appid(store, gid)
                ui(lambda: appid and info.winfo_exists() and verdict_label(info, appid))
            threading.Thread(target=find_appid, daemon=True).start()
            return
        tk.Label(info, text=f"Bottle: {b}  ·  {ENGINE_NAMES[engine(b)]}  ·  graphics: {RENDERERS.get(graphics(b), graphics(b))}",
                 bg=SIDE, fg=DIM).pack(anchor="w")
        if own := set_game(b, target):
            tk.Label(info, text="This game: " + ", ".join(f"{k} {v}" for k, v in own.items()), bg=SIDE, fg=DIM).pack(anchor="w")
        if appid := steam_appid_of(b, title):
            verdict_label(info, appid, b)
        bar = tk.Frame(detail, bg=SIDE)
        bar.pack(side="right", padx=24)
        added = title in library().get(b, {})
        files = target if not target.lower().endswith(".lnk") else str(win_to_mac(b, lnk_target(target) or "C:\\"))
        for text, fn, acc in [("▶  Play", lambda: play(item), True),
                              ("Game Settings…", lambda: game_settings_dialog(b, target, title), False),
                              ("Make Mac App", lambda: messagebox.showinfo("Windows Portal", f"Created {mac_app(b, target, title)}"), False),
                              ("Show Files", lambda: subprocess.run(["open", "-R", files]), False),
                              (("Remove", lambda: (remove_program(b, title), refresh())) if added else
                               ("Uninstall…", lambda: run(b, "uninstaller", wait=False))) + (False,)]:
            button(bar, text, fn, acc).pack(side="left", padx=4)

    # ---------- actions ----------
    def do_install():
        n = pick_bottle()
        if not n:
            return
        top = tk.Toplevel(root)
        top.title(f"Install into {n}")
        lb = tk.Listbox(top, width=40, height=12)
        lb.pack(padx=8, pady=8)
        for k in catalog():
            lb.insert("end", k)

        def go():
            if s := lb.curselection():
                item = lb.get(s[0])
                top.destroy()
                bg(f"Installing {item} into {n}…", install, n, item)
        def from_file():
            f = filedialog.askopenfilename(parent=top, title=f"Install into {n}", filetypes=[
                ("Installers and archives", " ".join(f"*{e}" for e in (".exe", ".msi", *ARCHIVES))), ("All", "*")])
            if f:
                top.destroy()
                bg(f"Installing {Path(f).name} into {n}…", install_file, n, f)
        row = tk.Frame(top)
        row.pack(pady=(0, 8))
        tk.Button(row, text="Install Selected", command=go).pack(side="left", padx=4)
        tk.Button(row, text="Install from File…", command=from_file).pack(side="left", padx=4)

    def do_add():
        n = pick_bottle()
        f = n and filedialog.askopenfilename(title=f"Add a program to {n}",
                                             filetypes=[("Windows programs", "*.exe *.lnk *.bat"), ("All", "*")])
        t = f and simpledialog.askstring("Add Program", "Name in library:", initialvalue=Path(f).stem)
        if t:
            add_program(n, f, t)
            refresh()

    def manage():
        if state["manager"]:
            return
        top = tk.Toplevel(root)
        top.title("Manage Bottles")
        bl = tk.Listbox(top, width=24, height=16, exportselection=False)
        bl.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        bar = tk.Frame(top)
        bar.pack(side="right", fill="y", padx=8, pady=8)

        def fill():
            bl.delete(0, "end")
            for b in bottles():
                bl.insert("end", f"{b}  ({engine(b)}, {graphics(b)})")
        state["manager"] = fill
        top.protocol("WM_DELETE_WINDOW", lambda: (state.update(manager=None), top.destroy()))

        def sel():
            s = bl.curselection()
            if not s:
                messagebox.showinfo("Windows Portal", "Select a bottle first.", parent=top)
            return bl.get(s[0]).rsplit("  (", 1)[0] if s else None

        def do_new():
            n = simpledialog.askstring("New bottle", "Bottle name:", parent=top)
            v = n and simpledialog.askstring("New bottle", "Windows version (win10, win11, win7, winxp64…):",
                                             initialvalue="win10", parent=top)
            e = v and ask_engine(f"Engine for {n}", next((e for e in ("wine10", "wine") if ENGINES[e].exists()), "gptk"))
            if e:
                bg(f"Creating {n}…", new, n, v, e)

        def ask_engine(title, current):
            e = simpledialog.askstring(title, "Engine:\n" + "\n".join(f"  {k} = {v}" for k, v in ENGINE_NAMES.items()),
                                       initialvalue=current, parent=top)
            if e and e not in ENGINES:
                messagebox.showerror("Windows Portal", f"Unknown engine {e!r}", parent=top)
                return None
            return e

        def do_winver():
            n = sel()
            v = n and simpledialog.askstring(
                f"Windows version for {n}", f"Currently: {winver(n)}\n\nNew version (win11, win10, win81, win7, winxp64…).\n"
                "Restart the bottle's programs afterwards.", initialvalue="win10", parent=top)
            if v:
                bg(f"Setting {n} to {v}…", winver, n, v)

        def do_keys():
            n = sel()
            on = n and messagebox.askyesnocancel(
                f"Keyboard for {n}", f"Currently {keys(n)}.\n\nMake Command act as Ctrl (⌘C, ⌘V, ⌘A work) and Option as Alt?\n"
                "No restores Wine's default, where Command acts as Alt. Restart the bottle's programs afterwards.", parent=top)
            if on is not None:
                bg(f"Updating {n}…", keys, n, on)

        def do_graphics():
            n = sel()
            if not n:
                return
            opts = GRAPHICS[engine(n)]
            g = simpledialog.askstring(f"Graphics for {n}", f"Currently: {graphics(n)}\n\n" + "\n".join(
                f"  {o} = {RENDERERS[o]}" for o in opts) + ("\n\nDXMT and DXVK need the wine10 engine." if engine(n) == "gptk" else "")
                + "\nRestart the bottle's programs afterwards.", initialvalue=graphics(n), parent=top)
            if not g or g == graphics(n):
                return
            if g == "d3dmetal" and engine(n) == "wine10" and not d3dmetal_accepted():
                if not messagebox.askyesno("D3DMetal license", D3DMETAL_LICENSE + "\n\nAccept?", parent=top):
                    return
                accept_d3dmetal(ask=False)
            bg(f"Setting {n} to {g}…", set_graphics, n, g)

        def do_sync():
            n = sel()
            m = n and simpledialog.askstring(
                f"Sync mode for {n}", f"Currently: {sync_mode(n)}\n\nmsync: fastest for games\nesync: in between\n"
                "none: needed for Steam's own window on this engine", initialvalue=sync_mode(n), parent=top)
            if m:
                bg(f"Setting {n} to {m}…", sync_mode, n, m)

        def do_display():
            n = sel()
            m = n and simpledialog.askstring(
                f"Display for {n}", f"Currently: {display(n)}\n\nstandard: Wine's default, fastest\nretina: full resolution, "
                "sharp\ncompact: full resolution, smaller text\n\nRestart the bottle's programs afterwards.",
                initialvalue=display(n), parent=top)
            if m:
                bg(f"Setting {n} to {m}…", display, n, m)

        def do_engine():
            n = sel()
            e = n and ask_engine(f"Engine for {n}", engine(n))
            if e and e != engine(n):
                set_engine(n, e)
                refresh()

        def do_run():
            n = sel()
            exe = n and filedialog.askopenfilename(parent=top, filetypes=[("Windows programs", "*.exe *.msi *.bat *.lnk"), ("All", "*")])
            if exe:
                run(n, exe, wait=False)

        def do_export():
            n = sel()
            d = n and filedialog.asksaveasfilename(parent=top, initialfile=f"{n}.tar.gz", filetypes=[("Bottle archive", "*.tar.gz")])
            if d:
                bg(f"Exporting {n}…", export, n, d.removesuffix(".tar.gz"))

        def do_import():
            f = filedialog.askopenfilename(parent=top, filetypes=[("Bottle archive", "*.tar.gz")])
            if f:
                bg("Importing…", import_, f)

        def do_delete():
            n = sel()
            if n and messagebox.askyesno("Delete", f"Permanently delete bottle {n}, its Mac apps and everything installed in it?", parent=top):
                state["filter"] = None if state["filter"] == n else state["filter"]
                bg(f"Deleting {n}…", delete, n)

        if not ENGINES["wine10"].exists():
            tk.Button(bar, text="Get Wine 10 Engine", width=16, command=guarded(
                lambda: bg("Downloading the Wine 10 engine (~250 MB)…", get_engine, "wine10"))).pack(pady=2)
        if not ENGINES["arm64"].exists():
            def get_native():
                if why := arm64_missing():
                    return messagebox.showinfo("Native engine", why[0].upper() + why[1:] + ".", parent=top)
                if messagebox.askyesno("Native engine (preview)", "Wine built for Apple Silicon: Windows programs run "
                                       "through FEX instead of Rosetta. Graphics are vkd3d-proton and DXVK only (no D3DMetal "
                                       "or DXMT), so many games run slower than on wine10 for now. It uses Highball's signed "
                                       "loader, and bottles can't move to it: make a new one.\n\nDownload it (~415 MB)?", parent=top):
                    bg("Downloading the native engine (~415 MB)…", get_engine, "arm64")
            tk.Button(bar, text="Get Native Engine…", width=16, command=guarded(get_native)).pack(pady=2)
        for label, fn in [("New Bottle…", do_new),
                          ("Run Program…", do_run),
                          ("Open C: Drive", lambda: (n := sel()) and drive_c(n)),
                          ("Engine…", do_engine),
                          ("Windows Version…", do_winver),
                          ("Graphics…", do_graphics),
                          ("Sync Mode…", do_sync),
                          ("Display…", do_display),
                          ("Repair Steam", lambda: (n := sel()) and bg(f"Repairing Steam in {n}… (up to 3 minutes)",
                                                                       lambda: ui(messagebox.showinfo, "Windows Portal", steam_repair(n)))),
                          ("Mac Shortcuts…", do_keys),
                          ("Wine Config", lambda: (n := sel()) and run(n, "winecfg", wait=False)),
                          ("Winetricks", lambda: (n := sel()) and bg("Winetricks open…", tricks, n)),
                          ("Force Quit", lambda: (n := sel()) and kill(n)),
                          ("Export…", do_export),
                          ("Import…", do_import),
                          ("Delete Bottle", do_delete)]:
            tk.Button(bar, text=label, width=16, command=guarded(fn)).pack(pady=2)
        fill()

    for text, fn, acc in [("Manage Bottles…", manage, False), ("Add Program…", do_add, False),
                          ("Install Software…", do_install, True)]:
        button(acts, text, fn, acc).pack(side="bottom", fill="x", pady=3)

    refresh()
    poll()
    root.mainloop()


if __name__ == "__main__":
    cmd, *a = sys.argv[1:] or ["gui"]
    cmds = {"gui": gui, "setup": setup, "package": package,
            "engine": lambda n, e=None: set_engine(n, e) if e else print(engine(n)),
            "winver": lambda n, v=None: print(winver(n, v)), "keys": lambda n, v=None: print(keys(n, v)),
            "store": store_cli, "get-engine": get_engine, "accept-d3dmetal": accept_d3dmetal,
            "display": lambda n, m=None: print(display(n, m)), "copy-games": lambda s, d: print("\n".join(copy_games(s, d))), "steam-repair": lambda n: print(steam_repair(n)),
            "game": lambda n, prog, k=None, v=None: print(set_game(n, prog, k, v)), "art-key": lambda k=None: print(art_key(k)),
            "graphics": lambda n, g=None: print(set_graphics(n, g) if g else graphics(n)),
            "sync": lambda n, m=None: print(sync_mode(n, m)),
            "compat": lambda g, *more: print(compat_report(" ".join((g, *more)))), "new": new, "run": run, "tricks": tricks, "install": install, "steam-sync": lambda: print(sync_steam()), "add": add_program, "remove": remove_program,
            "app": lambda n, f, t=None: print(mac_app(n, f, t)), "kill": kill, "export": export,
            "import": import_, "delete": delete, "c": drive_c, "config": lambda n: run(n, "winecfg"),
            "list": lambda: print("\n".join(bottles())), "catalog": lambda: print("\n".join(catalog())),
            "programs": lambda n: print("\n".join(f"{k}\t{v}" for k, v in programs(n).items()))}
    if cmd not in cmds:
        sys.exit(__doc__)
    cmds[cmd](*a)
