# progress.md: ThesisAgents

Outstanding work only. When an item is done, delete it in the same commit and add a `#done` entry to `docs/updates/` (format and query commands: `docs/updates/README.md`). No finished items, no history, no rules (rules live in `CLAUDE.md`).
Item numbers (`#n`) are never reused. Tags: [DECIDE] needs the owner's decision, [BLOCKED] waits on something else, [UNVERIFIED] observed but not confirmed.
Cross-repo and workspace items live in `D:\Codes\progress.md` (none open at the moment).

## Open

- **#4** The search-quality evaluator exists but no benchmark judgement file (qrels) is committed.
- **#5** [UNVERIFIED] The first release after U-20260925-01 builds cold (the cache key's paths changed). On the release after that, check the Nuitka log line `Compiled N C files using clcache with H cache hits` and the job time: if the build is warm, replace the expected ~5–10 min in `docs/releases.md` and the README (all 14 languages) with the measured value. If hits stay low, clcache's default 1 GiB size limit (`MaximumCacheSize` in Nuitka's inline `clcache/caching.py`) may be evicting objects.
- **#18** [UNVERIFIED] Deck templates have only been exercised with templates derived from python-pptx's stock file (layouts renamed, a title placeholder moved, slide size changed), and the resulting decks were checked by the overflow inspector, the contrast audit and a python-pptx round trip, not by eye: this machine has neither PowerPoint nor LibreOffice. Open question: how a real institutional template behaves, in particular one with a picture background, a dark background in light mode, or a title placeholder that inherits its position from the master. Check by exporting a rich deck on such a template and looking at it in PowerPoint.

### GUI roadmap (after the 2026-11-19 rebuild, U-20261119-01)

The rebuilt window (sidebar, light / dark / system theme, layouts that adapt to the width) changed how the GUI looks, not what it can do. The items below are the gaps between the GUI and the CLI / MCP surfaces, plus improvements to what the GUI already does, in suggested order.

- **#28** [UNVERIFIED] The rebuilt GUI has been checked by the test suite and by offscreen renders at 680, 1000 and 1400 px in both themes and both styles (classic, Material 3), not on a real screen. Open: how it looks and behaves at 100 / 125 / 150 / 200 % Windows scaling, with the OS switching between light and dark while the app is open, on macOS and Linux, and with a screen reader (every input needs an accessible name, the focus order should follow the cards). Check by running `thesisagents gui` on such setups and fix what does not hold.
