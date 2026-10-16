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
