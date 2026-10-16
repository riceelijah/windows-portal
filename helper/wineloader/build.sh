#!/bin/zsh
# Builds the arm64 Wine loader (main.c) into build/wineloader/wine. Needs Xcode 26.4 or later (-x86_64_layout_emulation).
# Flags, as Highball measured them (M4, macOS 27.0, 2026-10-04):
# - SDK version 11.0 in the platform_version load command: a binary built against an SDK of 26.5 or later loses x18,
#   the register Windows ARM64 code keeps its thread block in, across context switches.
# - PAGEZERO and image base at 0x170000000 with the layout flag: Wine's default 4 KB segment alignment is killed at
#   exec on arm64, and the big PAGEZERO needs the raised base.
# - Wine's Info.plist embedded: child processes start through a symlink in the engine, where Cocoa finds no bundle.
set -euo pipefail
cd "$(dirname "$0")/../.."
OUT=build/wineloader; mkdir -p "$OUT"
MACOSX_DEPLOYMENT_TARGET=11.0 clang -arch arm64 -O2 -Wall -mmacos-version-min=11.0 \
  -o "$OUT/wine" helper/wineloader/main.c \
  -Wl,-platform_version,macos,11.0,11.0 \
  -Wl,-pagezero_size,0x170000000 -Wl,-image_base,0x170000000 -Wl,-x86_64_layout_emulation \
  -Wl,-sectcreate,__TEXT,__info_plist,helper/wineloader/wine_info.plist 2> "$OUT/build.log" \
  || { cat "$OUT/build.log" >&2; exit 1; }
grep -v "pagezero_size is too large\|prefered load addresses\|^$" "$OUT/build.log" >&2 || true  # these two are expected
otool -l "$OUT/wine" | grep -A3 "segname __PAGEZERO" | grep -q "vmsize 0x0000000170000000" \
  || { echo "error: the loader's PAGEZERO is not 0x170000000" >&2; exit 1; }
echo "built $OUT/wine"
