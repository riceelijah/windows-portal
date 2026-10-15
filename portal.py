#!/usr/bin/env python3
"""Windows Portal: a free CrossOver-style bottle manager on top of Wine.

  python3 portal.py                        # GUI
  python3 portal.py setup                  # install Wine (Game Porting Toolkit) + winetricks
  python3 portal.py package [DIR]          # build "Windows Portal.app" (default ~/Applications)
  python3 portal.py new NAME [WINVER] [ENGINE]  # WINVER: win10 (default), win11, win7, winxp64...
                                           # ENGINE: wine (Wine 11, default) or gptk (DirectX 12 games)
  python3 portal.py engine NAME [ENGINE]   # show or switch a bottle's engine
  python3 portal.py winver NAME [WINVER]   # show or change the Windows version (restart its programs after)
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
  python3 portal.py import ARCHIVE
  python3 portal.py delete NAME

Every bottle is 64-bit and runs 32-bit programs too (WoW64); this Wine can't make pure 32-bit bottles.
Add your own installers to ~/Library/Application Support/WindowsPortal/catalog.json:
  {"My App": {"url": "https://.../setup.exe", "file": "myapp-setup.exe", "tricks": ["vcrun2022"]}}
"""
import base64, json, os, re, zlib, plistlib, shlex, shutil, subprocess, sys, tarfile, urllib.request
from pathlib import Path

DATA = Path.home() / "Library/Application Support/WindowsPortal"
HOME = DATA / "bottles"
CACHE = Path.home() / "Library/Caches/WindowsPortal"
APPS = Path.home() / "Applications/Windows Portal"
WINE_VERSION = "11.18"  # Gcenx/macOS_Wine_builds, the official WineHQ macOS packages
WINE_URL = f"https://github.com/Gcenx/macOS_Wine_builds/releases/download/{WINE_VERSION}/wine-devel-{WINE_VERSION}-osx64.tar.xz"
WINE_SHA256 = "aa0ea4c82e636ae7bca2076387cb0a5affa26509ad13f119ecd0d62bd7ba6f82"
ENGINES = {  # per bottle; GPTK is the one with D3DMetal, so DirectX 12 games go there
    "wine": DATA / f"engines/wine-{WINE_VERSION}/Wine Devel.app/Contents/Resources/wine/bin/wine",
    "gptk": Path("/Applications/Game Porting Toolkit.app/Contents/Resources/wine/bin/wine64"),
}
ENGINE_NAMES = {"wine": f"Wine {WINE_VERSION}", "gptk": "Game Porting Toolkit (DirectX 12)"}

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


def engine(name):
    cfg = bottle(name) / "portal.json"
    return json.loads(cfg.read_text())["engine"] if cfg.exists() else "gptk"  # pre-engine bottles were GPTK


def set_engine(name, eng):
    if eng not in ENGINES:
        sys.exit(f"unknown engine {eng!r}; choose from: {', '.join(ENGINES)}")
    if (bottle(name) / "portal.json").exists():
        if engine(name) == "wine" and eng == "gptk" and (bottle(name) / "system.reg").exists():
            sys.exit(f"{name} has been upgraded by Wine {WINE_VERSION}; GPTK's older Wine can't open it reliably. "
                     "Make a new bottle with the gptk engine instead.")
        kill(name)  # stop the old engine's wineserver before the other one touches the bottle
    (bottle(name) / "portal.json").write_text(json.dumps({"engine": eng}))


def wine(name):
    p = ENGINES[engine(name)]
    if not p.exists():
        sys.exit(f"{ENGINE_NAMES[engine(name)]} isn't installed. Run: python3 portal.py setup")
    return str(p)


def bottle(name, exists=True):
    if not name or "/" in name or name.startswith("."):
        sys.exit(f"bad bottle name: {name!r}")
    if exists and not (HOME / name).is_dir():
        sys.exit(f"no bottle {name}")
    return HOME / name


def wine_env(name):
    # Speed/memory: no debug logging, esync/msync instead of wineserver round-trips for every lock,
    # no winemenubuilder (it spawns per install and litters ~/.local), AVX advertised to Rosetta for games.
    return {"WINEPREFIX": str(bottle(name)), "WINEDEBUG": "-all", "WINEESYNC": "1", "WINEMSYNC": "1",
            # gameoverlayrenderer: Steam's in-game overlay hangs games under Wine (Portal spun at 100% CPU, no window).
            # Steam passes its environment to the games it launches, so this covers them too.
            "WINEDLLOVERRIDES": os.environ.get("WINEDLLOVERRIDES", "winemenubuilder.exe=d;gameoverlayrenderer=d"),
            "ROSETTA_ADVERTISE_AVX": "1"}


def env(name):
    return {**os.environ, **wine_env(name)}


def setup():
    # Homebrew's own Wine casks were disabled 2026-09-01 (Gatekeeper); Gcenx's GPTK build still installs.
    subprocess.run(["brew", "tap", "gcenx/wine"], check=True)
    subprocess.run(["brew", "trust", "gcenx/wine"], check=True)
    subprocess.run(["brew", "install", "--cask", "game-porting-toolkit"], check=True)
    subprocess.run(["brew", "install", "winetricks"], check=True)
    if not ENGINES["wine"].exists():
        import hashlib
        tarball = download(WINE_URL, f"wine-devel-{WINE_VERSION}.tar.xz")
        h = hashlib.sha256()
        with open(tarball, "rb") as f:
            while chunk := f.read(1 << 20):
                h.update(chunk)
        if h.hexdigest() != WINE_SHA256:
            tarball.unlink()
            sys.exit("Wine download failed its checksum; deleted it, run setup again")
        dest = DATA / f"engines/wine-{WINE_VERSION}"
        dest.mkdir(parents=True, exist_ok=True)
        subprocess.run(["tar", "-xf", str(tarball), "-C", str(dest)], check=True)
        tarball.unlink()


def bottles():
    return sorted(p.name for p in HOME.iterdir() if p.is_dir()) if HOME.exists() else []


def new(name, winver="win10", eng=None):
    p = bottle(name, exists=False)
    eng = eng or ("wine" if ENGINES["wine"].exists() else "gptk")
    if p.exists():
        sys.exit(f"bottle {name} already exists")
    if not ENGINES.get(eng, Path("/nonexistent")).exists():
        sys.exit(f"engine {eng!r} isn't available; choose from: {', '.join(e for e, p in ENGINES.items() if p.exists())}")
    p.mkdir(parents=True)
    set_engine(name, eng)
    w = wine(name)
    subprocess.run([w, "wineboot", "--init"], env=env(name), check=True)
    subprocess.run([w, "winecfg", "-v", winver], env=env(name), check=True)


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
    w = wine(name)
    if appid := steam_appid(name, exe):  # Steam games launch through Steam: it adds their launch options and DRM
        exe, args = "steam.exe", ("-applaunch", appid, *args)
    if steam := steam_exe(name, exe):  # -noverifyfiles: else Steam "repairs" the stand-in at startup
        fix_steam(name)
        exe, args = str(steam), ("-noverifyfiles", *args)
    low = exe.lower()
    cmd = ([w, "msiexec", "/i", exe] if low.endswith(".msi") else
           [w, "start", "/unix", exe] if low.endswith(".lnk") else [w, exe])
    proc = subprocess.Popen([*cmd, *args], env=env(name), cwd=Path(exe).parent if os.path.exists(exe) else None)
    return proc.wait() if wait else proc


def tricks(name, *verbs):
    bottle(name)
    wt = shutil.which("winetricks") or sys.exit("winetricks not found. Run: python3 portal.py setup")
    subprocess.run([wt, *(verbs or ["--gui"])], env={**env(name), "WINE": wine(name)})


def kill(name):
    try:
        w = wine(name)
    except SystemExit:
        return  # engine not installed, so nothing of this bottle can be running
    subprocess.run([str(Path(w).with_name("wineserver")), "-k"], env=env(name))


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
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as r, open(dest.with_suffix(".part"), "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)  # streamed, never the whole installer in memory
        dest.with_suffix(".part").rename(dest)
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


def install_file(name, path):
    """Runs an installer, or unpacks an archive into C:\\Games and installs/registers what's inside."""
    bottle(name)
    before, low = programs(name), path.lower()
    if low.endswith((".exe", ".msi", ".bat")):
        run(name, path)
        # ponytail: an exe that makes no shortcut is assumed portable; an installer that silently
        # skips shortcuts lands in the library as its setup.exe, Remove + Add Program fixes it.
        return register_new(name, before, fallback=None if low.endswith(".msi") else path)
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
    return register_new(name, before, fallback=str(main), title=stem)


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
        if uses_dx12(folder):
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


def mac_app(name, target, title=None):
    title = (title or Path(target).stem).replace("/", "-")
    app = APPS / f"{title}.app"
    owner = app / "Contents/MacOS/launch"
    if owner.exists() and f"WINEPREFIX={shlex.quote(str(bottle(name)))} " not in owner.read_text():
        app = APPS / f"{title} ({name}).app"  # same program in another bottle: don't clobber its app
    (app / "Contents/MacOS").mkdir(parents=True, exist_ok=True)
    exports = " ".join(f"{k}={shlex.quote(v)}" for k, v in wine_env(name).items())
    script = app / "Contents/MacOS/launch"
    launch, fix = shlex.quote(target), ""
    appid = steam_appid(name, target)
    if steam := steam_exe(name, "steam.exe" if appid else target):  # same as fix_steam() and run(), in shell so it repeats after Steam updates
        (DATA / "steamwebhelper.exe").write_bytes(WEBHELPER)
        w, d = shlex.quote(str(DATA / "steamwebhelper.exe")), shlex.quote(str(steam.parent / "bin/cef/cef.win64"))
        fix = f'cmp -s {w} {d}/steamwebhelper.exe || {{ mv -f {d}/steamwebhelper.exe {d}/steamwebhelper_real.exe && cp {w} {d}/steamwebhelper.exe; }}\n'
        launch = f"{shlex.quote(str(steam))} -noverifyfiles" + (f" -applaunch {appid}" if appid else "")
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


def lnk_icon(path):
    """(icon file, icon index) from a Windows .lnk, per [MS-SHLLINK]."""
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
    icon = dict(strings).get(0x40)
    return (icon, index) if icon and "%" not in icon else (target, 0)


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
    state = {"filter": None, "selected": None, "items": [], "tiles": [], "manager": None}
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
        if state["filter"]:
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
        rows = [(None, "All Programs")] + ([("", "BOTTLES")] if bottles() else []) + [(b, b) for b in bottles()]
        for key, text in rows:
            if key == "":
                tk.Label(nav, text=text, bg=SIDE, fg=DIM, font=("Helvetica", 10, "bold")).pack(anchor="w", padx=18, pady=(14, 4))
                continue
            on = key == state["filter"]
            l = tk.Label(nav, text=text, anchor="w", bg=HOVER if on else SIDE, fg=FG if on else DIM,
                         padx=18, pady=7, font=("Helvetica", 13))
            l.pack(fill="x")
            l.bind("<Button-1>", lambda e, k=key: (state.update(filter=k, selected=None), draw_nav(), draw()))

    def draw():
        for f, *_ in state["tiles"]:
            f.destroy()
        q = query.get().lower()
        shown = [i for i in state["items"] if state["filter"] in (None, i[1]) and q in i[0].lower()]
        heading.config(text=state["filter"] or "All Programs")
        state["tiles"] = [tile(i) for i in shown]
        if not shown:
            f = tk.Label(grid, bg=BG, fg=DIM, font=("Helvetica", 14), pady=40,
                         text="No programs here yet.\nUse Install Software or Add Program on the left.")
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
        run(b, target, wait=False)
        status.set(f"Launched {title}")
        root.after(4000, lambda: status.get() == f"Launched {title}" and status.set(""))

    def show_detail():
        for w in detail.winfo_children():
            w.destroy()
        item = state["selected"] if state["selected"] in state["items"] else None
        if not item:
            tk.Label(detail, text="Select a program to see its options. Double-click to play.",
                     bg=SIDE, fg=DIM, font=("Helvetica", 13)).pack(padx=24, pady=44, anchor="w")
            return
        title, b, target, _ = item
        info = tk.Frame(detail, bg=SIDE)
        info.pack(side="left", padx=24)
        tk.Label(info, text=title, bg=SIDE, fg=FG, font=("Helvetica", 20, "bold")).pack(anchor="w")
        tk.Label(info, text=f"Bottle: {b}  ·  {ENGINE_NAMES[engine(b)]}", bg=SIDE, fg=DIM).pack(anchor="w")
        bar = tk.Frame(detail, bg=SIDE)
        bar.pack(side="right", padx=24)
        added = title in library().get(b, {})
        files = target if not target.lower().endswith(".lnk") else str(win_to_mac(b, lnk_icon(target)[0] or "C:\\"))
        for text, fn, acc in [("▶  Play", lambda: play(item), True),
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
                bl.insert("end", f"{b}  ({engine(b)})")
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
            e = v and ask_engine(f"Engine for {n}", "wine" if ENGINES["wine"].exists() else "gptk")
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

        for label, fn in [("New Bottle…", do_new),
                          ("Run Program…", do_run),
                          ("Open C: Drive", lambda: (n := sel()) and drive_c(n)),
                          ("Engine…", do_engine),
                          ("Windows Version…", do_winver),
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
            "winver": lambda n, v=None: print(winver(n, v)), "new": new, "run": run, "tricks": tricks, "install": install, "steam-sync": lambda: print(sync_steam()), "add": add_program, "remove": remove_program,
            "app": lambda n, f, t=None: print(mac_app(n, f, t)), "kill": kill, "export": export,
            "import": import_, "delete": delete, "c": drive_c, "config": lambda n: run(n, "winecfg"),
            "list": lambda: print("\n".join(bottles())), "catalog": lambda: print("\n".join(catalog())),
            "programs": lambda n: print("\n".join(f"{k}\t{v}" for k, v in programs(n).items()))}
    if cmd not in cmds:
        sys.exit(__doc__)
    cmds[cmd](*a)
