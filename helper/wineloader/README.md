# Wine loader helper

`main.c` is Wine 11.18's `loader/main.c` with two changes, from
[Highball](https://github.com/gauthierpiarrette/highball) (`spike/wineloader/main.c` at commit b2c1e0dd), copied
unchanged. It is **LGPL-2.1-or-later** like the rest of Wine (see `COPYING.LIB`), and it stays a separate program
from Windows Portal. `wine_info.plist` is Wine's own.

The two changes:
1. **Memory layout.** On arm64 it hands Wine the `__PAGEZERO` range as reserved low memory, where 32-bit and 64-bit
   Windows programs expect theirs.
2. **Finding the engine.** It looks for `ntdll.so` beside the path it was started through, one symlink hop at a time.
   That lets one signed copy inside `Windows Portal.app` serve every native engine, whose loaders become symlinks
   to it.

Why it exists: on Apple Silicon, a Wine that runs x86 code natively needs Apple's cross-architecture entitlement
(`com.apple.developer.cross-architecture-support`). The kernel honours it only on a signed bundle that carries a
matching provisioning profile, so the loader can't live inside a downloaded engine. `build.sh` builds it, and
`scripts/build-app.sh` bundles it as `Windows Portal.app/Contents/Helpers/WineLoader.app` and signs it.
